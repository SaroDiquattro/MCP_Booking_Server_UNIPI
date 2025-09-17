#!/usr/bin/env python3
"""
Tool per gestione prenotazioni e controllo disponibilità
"""

import json
import logging
import os
from datetime import datetime
from decimal import Decimal

from database import get_db_connection, convert_decimals, resolve_resource_info

logger = logging.getLogger(__name__)

def get_calendar_codes():
    """Ottieni i codici calendario dalla variabile d'ambiente"""
    calendar_codes = os.getenv('CALENDAR_CODES')
    return [code.strip() for code in calendar_codes.split(',')]

async def get_active_bookings(start_time: str, end_time: str) -> str:
    """Ottieni tutte le prenotazioni attive in un periodo
    
    Args:
        start_time: Data/ora inizio formato YYYY-MM-DD HH:MM
        end_time: Data/ora fine formato YYYY-MM-DD HH:MM
    """
    try:
        # Converti stringhe in datetime
        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")

        # Ottieni i codici calendario
        calendar_codes = get_calendar_codes()
        
        # Query database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT 
                T1.tetitle AS evento, 
                T1.tetaskid AS id_evento, 
                T2.cacodcal AS cod_calendario, 
                T2.cadescri AS nome_calendario,
                T1.telocation AS location,
                T1.telisris AS lista_risorse,
                T1.teprevbegin AS inizio, 
                T1.teprevend AS fine, 
                EXTRACT(EPOCH FROM (T1.teprevend - T1.teprevbegin))/3600 AS durata_ore 
            FROM tasks T1 
            JOIN calendar T2 ON T1.tecodcal = T2.cacodcal 
            WHERE T1.teprevbegin <= %s 
                AND T1.teprevend >= %s
                AND T1.testato = 'C'
                AND T2.cacodcal IN (%s, %s, %s)
            ORDER BY T2.cadescri, T1.teprevbegin
        """
        
        cursor.execute(query, (end_dt, start_dt) + tuple(calendar_codes) )
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Organizza risultati
        bookings_by_resource = {}
        total_events = 0
        total_hours = 0

        for booking in results:
            cod_cal = booking['cod_calendario']
            
            if cod_cal not in bookings_by_resource:
                bookings_by_resource[cod_cal] = {
                    'nome_calendario': booking['nome_calendario'],
                    'eventi': [],
                    'ore_totali': 0
                }
            
            # Converti Decimal in float
            durata_ore = float(booking['durata_ore']) if isinstance(booking['durata_ore'], Decimal) else booking['durata_ore']
            
            evento_info = {
                'evento': booking['evento'],
                'id_evento': booking['id_evento'],
                'inizio': booking['inizio'].strftime('%Y-%m-%d %H:%M'),
                'fine': booking['fine'].strftime('%Y-%m-%d %H:%M'),
                'durata_ore': round(durata_ore, 1),
                'risorse_impegnate': booking['lista_risorse']
            }
            
            bookings_by_resource[cod_cal]['eventi'].append(evento_info)
            bookings_by_resource[cod_cal]['ore_totali'] += durata_ore
            
            total_events += 1
            total_hours += durata_ore

        for cod_cal in bookings_by_resource:
            bookings_by_resource[cod_cal]['ore_totali'] = round(bookings_by_resource[cod_cal]['ore_totali'], 1)
        
        # Formatta risultato
        result = {
            'periodo': {
                'inizio': start_time,
                'fine': end_time,
                'durata_totale_ore': round((end_dt - start_dt).total_seconds() / 3600, 1)
            },
            'riepilogo': {
                'risorse_impegnate': len(bookings_by_resource),
                'eventi_totali': total_events,
                'ore_totali': round(total_hours, 1)
            },
            'risorse': bookings_by_resource
        }
        
        return json.dumps(convert_decimals(result), indent=2, ensure_ascii=False)
        
    except Exception as e:
        logger.error(f"Errore in get_active_bookings: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)

async def check_resource_availability(resource: str, start_time: str, end_time: str) -> str:
    """Verifica se una determinata risorsa è disponibile in un orario specifico"""
    try:
        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
        
        resource_info = await resolve_resource_info(resource)
        
        if resource_info['type'] == 'not_found':
            return json.dumps({
                "error": f"Risorsa '{resource}' non trovata"
            }, ensure_ascii=False)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if resource_info['type'] == 'exact':
            # Caso semplice: una risorsa specifica
            resource_id = resource_info['resources'][0]['reresourceid']
            query = """
                SELECT COUNT(*) as conflitti
                FROM resourcelist r
                WHERE r.rlresourceid = %s
                AND (r.rlprevbegin < %s AND r.rlprevend > %s)
            """
            cursor.execute(query, (resource_id, end_dt, start_dt))
            
        else:
            # Caso complesso: multiple risorse (es. tutte le Fiat)
            resource_ids = [r['reresourceid'] for r in resource_info['resources']]
            placeholders = ','.join(['%s'] * len(resource_ids))
            query = f"""
                SELECT r.rlresourceid, COUNT(*) as conflitti
                FROM resourcelist r
                WHERE r.rlresourceid IN ({placeholders})
                AND (r.rlprevbegin < %s AND r.rlprevend > %s)
                GROUP BY r.rlresourceid
            """
            cursor.execute(query, resource_ids + [end_dt, start_dt])
        
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Analizza risultati
        if resource_info['type'] == 'exact':
            is_available = results[0]['conflitti'] == 0
            response = {
                'risorsa': {
                    'ricerca_originale': resource,
                    'tipo': 'risorsa_specifica',
                    'id': resource_info['resources'][0]['reresourceid'],
                    'descrizione': resource_info['resources'][0]['redescri']
                },
                'disponibile': is_available,
                'conflitti': results[0]['conflitti']
            }
        else:
            # Multiple risorse: mostra stato di ognuna
            busy_resources = {r['rlresourceid']: r['conflitti'] for r in results}
            free_resources = []
            busy_list = []
            
            for res in resource_info['resources']:
                if res['reresourceid'] not in busy_resources:
                    free_resources.append(res['reresourceid'])
                else:
                    busy_list.append(res['reresourceid'])
            
            response = {
                'risorsa': {
                    'ricerca_originale': resource,
                    'tipo': 'ricerca_multipla',
                    'risorse_trovate': len(resource_info['resources']),
                    'elenco_risorse': [r['reresourceid'] for r in resource_info['resources']]
                },
                'risultato': {
                    'almeno_una_libera': len(free_resources) > 0,
                    'risorse_libere': free_resources,
                    'risorse_occupate': busy_list,
                    'totale_libere': len(free_resources),
                    'totale_occupate': len(busy_list)
                }
            }
        
        return json.dumps(response, indent=2, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)