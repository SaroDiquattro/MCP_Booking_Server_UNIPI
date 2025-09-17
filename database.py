#!/usr/bin/env python3
"""
Modulo per gestione connessioni database e utilità DB comuni
"""

import logging
import os
from typing import Dict
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

# Setup logging
logger = logging.getLogger(__name__)

# Configurazione database
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT')),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD')
}

# Validazione DB config
required_db_vars = ['DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']
for var in required_db_vars:
    if not os.getenv(var):
        raise ValueError(f"Variabile d'ambiente DB mancante: {var}")

def get_db_connection():
    """Ottiene connessione al database"""
    try:
        conn = psycopg2.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            database=DB_CONFIG['database'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        logger.error(f"Errore connessione database: {e}")
        raise

def test_connection():
    """Testa la connessione al database all'avvio"""
    try:
        logger.info(f"🔌 Test connessione a {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM calendar")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        logger.info(f"✅ Connessione OK - Trovati {result['count']} calendari")
        return True
    except Exception as e:
        logger.error(f"❌ Errore connessione: {e}")
        return False

def convert_decimals(obj):
    """Converte ricorsivamente tutti i Decimal in float per la serializzazione JSON"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(item) for item in obj]
    return obj

async def resolve_resource_info(resource: str) -> Dict:
    """Gestisce anche ricerche che corrispondono a più risorse"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Prima cerca ID esatto
    cursor.execute("""
        SELECT reresourceid, redescri, retype, recodcal 
        FROM resources 
        WHERE UPPER(reresourceid) = UPPER(%s) AND flactive = 1
    """, (resource,))
    
    exact_match = cursor.fetchone()
    if exact_match:
        cursor.close()
        conn.close()
        return {
            'type': 'exact',
            'resources': [exact_match],
            'calendar_code': exact_match['recodcal']
        }
    
    # Cerca per descrizione (TUTTE le corrispondenze)
    cursor.execute("""
        SELECT reresourceid, redescri, retype, recodcal 
        FROM resources 
        WHERE LOWER(redescri) LIKE LOWER(%s) AND flactive = 1
        ORDER BY reresourceid
    """, (f"%{resource}%",))
    
    matches = cursor.fetchall()
    cursor.close()
    conn.close()
    
    if matches:
        return {
            'type': 'multiple' if len(matches) > 1 else 'single',
            'resources': matches,
            'calendar_code': matches[0]['recodcal']  # Assumendo stesso calendario
        }
    
    return {'type': 'not_found'}