#!/usr/bin/env python3
"""
Tool per controllo stato salute del sistema
"""

import json
import logging
from datetime import datetime

from database import get_db_connection

logger = logging.getLogger(__name__)

async def health_check() -> str:
    """Controlla lo stato di salute del server e del database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Controlla calendari e risorse
        cursor.execute("SELECT COUNT(*) as count FROM calendar")
        cal_result = cursor.fetchone()
        
        cursor.execute("SELECT COUNT(*) as count FROM resources WHERE flactive = 1")
        res_result = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        response = {
            'status': 'healthy',
            'database_connection': 'ok',
            'calendari_totali': cal_result['count'],
            'risorse_attive': res_result['count'],
            'timestamp': datetime.now().isoformat()
        }
        
        return json.dumps(response, indent=2, ensure_ascii=False)
        
    except Exception as e:
        logger.error(f"Errore in health_check: {e}")
        return json.dumps({
            'status': 'unhealthy',
            'database_connection': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }, ensure_ascii=False)