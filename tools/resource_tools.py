#!/usr/bin/env python3
"""
Tool per gestione e ricerca risorse
"""

import json
import logging
import os
from datetime import datetime
from dotenv import load_dotenv

from database import get_db_connection

load_dotenv('parameters.env')

logger = logging.getLogger(__name__)

# Tipo delle risorse, parametro del server
ROOMS_TYPE = os.getenv('RESOURCE_TYPE_ROOMS')
VEHICLES_TYPE = os.getenv('RESOURCE_TYPE_VEHICLES')
PROJECTORS_TYPE = os.getenv('RESOURCE_TYPE_PROJECTORS')

async def list_available_resources() -> str:
    """Elenca tutte le risorse disponibili"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT reresourceid, redescri, retype, recodcal
            FROM resources 
            WHERE flactive = 1
            ORDER BY retype, redescri
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        resources = []
        for r in results:
            resources.append({
                'id': r['reresourceid'],
                'description': r['redescri'],
                'type': r['retype'],
                'calendar_code': r['recodcal']
            })
        
        response = {
            'total_resources': len(resources),
            'resources': resources
        }
        
        return json.dumps(response, indent=2, ensure_ascii=False)
        
    except Exception as e:
        logger.error(f"Errore in list_available_resources: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)

async def find_free_resources(start_time: str, end_time: str) -> str:
    """Trova tutte le risorse libere in un orario specifico"""
    try:
        # Converti stringhe in datetime
        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query corretta: trova risorse NON presenti nelle prenotazioni per il periodo
        query = """
            WITH busy_resources AS (
                SELECT DISTINCT r.rlresourceid
                FROM resourcelist r
                WHERE (r.rlprevbegin < %s AND r.rlprevend > %s)
            )
            SELECT res.reresourceid,res.redescri, res.retype,
                CASE 
                    WHEN res.retype = %s THEN 'Aule/Stanze'
                    WHEN res.retype = %s THEN 'Automezzi'
                    WHEN res.retype = %s THEN 'Proiettori'
                    ELSE 'Altro'
                END as tipo_descrizione
            FROM resources res
            WHERE res.flactive = 1 
            AND res.reresourceid NOT IN (SELECT rlresourceid FROM busy_resources WHERE rlresourceid IS NOT NULL)
            ORDER BY res.retype, res.reresourceid
        """
        
        cursor.execute(query, (end_dt, start_dt, ROOMS_TYPE, VEHICLES_TYPE, PROJECTORS_TYPE))
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Organizza per tipo
        resources_by_type = {}
        total_free = 0
        
        for r in results:
            tipo = r['tipo_descrizione']
            if tipo not in resources_by_type:
                resources_by_type[tipo] = []
            
            resources_by_type[tipo].append({
                'id': r['reresourceid'],
                'descrizione': r['redescri'],
                'tipo_codice': r['retype']
            })
            total_free += 1
        
        response = {
            'periodo_richiesto': {
                'inizio': start_time,
                'fine': end_time,
                'durata_ore': round((end_dt - start_dt).total_seconds() / 3600, 1)
            },
            'riepilogo': {
                'risorse_libere_totali': total_free,
                'tipi_disponibili': len(resources_by_type)
            },
            'risorse_per_tipo': resources_by_type
        }
        
        return json.dumps(response, indent=2, ensure_ascii=False)
        
    except Exception as e:
        logger.error(f"Errore in find_free_resources: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)