#!/usr/bin/env python3
"""
Server MCP standard per gestione prenotazioni
Solo modalità stdio - da usare con mcpo per OpenWebUI
"""

import asyncio
import json
import logging
from typing import List

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ServerCapabilities,
    ToolsCapability,
)

# Import moduli locali
from database import test_connection
from tools import (
    get_active_bookings,
    check_resource_availability,
    find_free_resources,
    list_available_resources,
    health_check,
    create_activity,
    update_activity
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Crea il server MCP
server = Server("booking-server")

@server.list_tools()
async def handle_list_tools() -> List[Tool]:
    """Lista tutti i tool disponibili"""
    return [
        Tool(
            name="get_active_bookings",
            description="Ottieni tutte le prenotazioni attive in un periodo",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Data inizio formato YYYY-MM-DD HH:MM"
                    },
                    "end_date": {
                        "type": "string", 
                        "description": "Data fine formato YYYY-MM-DD HH:MM"
                    }
                },
                "required": ["start_date", "end_date"]
            }
        ),
        Tool(
            name="check_resource_availability",
            description="Controlla se una risorsa è disponibile in un orario specifico. Puoi usare l'ID risorsa (es. AULA01) o parte della descrizione (es. 'aula corsi')",
            inputSchema={
                "type": "object",
                "properties": {
                    "resource": {
                        "type": "string",
                        "description": "ID risorsa (es. AULA01) o descrizione (es. 'aula corsi', 'proiettore')"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Orario inizio formato YYYY-MM-DD HH:MM"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "Orario fine formato YYYY-MM-DD HH:MM"
                    }
                },
                "required": ["resource", "start_time", "end_time"]
            }
        ),
        Tool(
            name="find_free_resources",
            description="Trova tutte le risorse libere in un orario specifico",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_time": {
                        "type": "string",
                        "description": "Orario inizio formato YYYY-MM-DD HH:MM"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "Orario fine formato YYYY-MM-DD HH:MM"
                    }
                },
                "required": ["start_time", "end_time"]
            }
        ),
        Tool(
            name="list_available_resources",
            description="Elenca tutte le risorse disponibili per la prenotazione",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="health_check",
            description="Controlla lo stato di salute del server e del database",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="create_activity",
            description="Crea una nuova attività/prenotazione per risorse (stanze, automezzi, proiettori). Controlla automaticamente la disponibilità e determina il tipo corretto.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Titolo dell'attività/prenotazione"
                    },
                    "resource_id": {
                        "type": "string",
                        "description": "ID della risorsa da prenotare (es. AULA01, FIAT01, PROJ01)"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Orario inizio formato YYYY-MM-DD HH:MM"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "Orario fine formato YYYY-MM-DD HH:MM"
                    },
                    "location": {
                        "type": "string",
                        "description": "Luogo dell'attività (opzionale, usa resource_id se non specificato)",
                        "default": ""
                    },
                    "description": {
                        "type": "string",
                        "description": "Descrizione dettagliata dell'attività (opzionale)",
                        "default": ""
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priorità 1-10 (default: 5)",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5
                    }
                },
                "required": ["title", "resource_id", "start_time", "end_time"]
            }
        ),
        Tool(
            name="update_activity",
            description="Aggiorna un'attività/prenotazione esistente. Richiede l'ID dell'attività (task_id) da modificare.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "ID dell'attività da aggiornare"
                    },
                    "title": {
                        "type": "string",
                        "description": "Titolo dell'attività/prenotazione"
                    },
                    "resource_id": {
                        "type": "string",
                        "description": "ID della risorsa da prenotare (es. AULA01, FIAT01, PROJ01)"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Orario inizio formato YYYY-MM-DD HH:MM"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "Orario fine formato YYYY-MM-DD HH:MM"
                    },
                    "location": {
                        "type": "string",
                        "description": "Luogo dell'attività (opzionale, usa resource_id se non specificato)",
                        "default": ""
                    },
                    "description": {
                        "type": "string",
                        "description": "Descrizione dettagliata dell'attività (opzionale)",
                        "default": ""
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priorità 1-10 (default: 5)",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5
                    }
                },
                "required": ["task_id", "title", "resource_id", "start_time", "end_time"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> List[TextContent]:
    """Gestisce le chiamate ai tool"""
    try:
        # Dizionario che mappa i nomi dei tool alle loro funzioni
        tool_handlers = {
            "get_active_bookings": lambda: get_active_bookings(
                arguments["start_date"], 
                arguments["end_date"]
            ),
            "check_resource_availability": lambda: check_resource_availability(
                arguments["resource"],
                arguments["start_time"],
                arguments["end_time"]
            ),
            "find_free_resources": lambda: find_free_resources(
                arguments["start_time"],
                arguments["end_time"]
            ),
            "list_available_resources": lambda: list_available_resources(),
            "health_check": lambda: health_check(),
            "create_activity": lambda: create_activity(
                arguments["title"],
                arguments["resource_id"], 
                arguments["start_time"],
                arguments["end_time"],
                arguments.get("location", ""),
                arguments.get("description", ""),
                arguments.get("priority", 5)
            ),
            "update_activity": lambda: update_activity(
                arguments["task_id"],
                arguments["title"],
                arguments["resource_id"], 
                arguments["start_time"],
                arguments["end_time"],
                arguments.get("location", ""),
                arguments.get("description", ""),
                arguments.get("priority", 5)
            )
        }
        
        # Esegue il tool appropriato
        if name in tool_handlers:
            result = await tool_handlers[name]()
        else:
            raise ValueError(f"Tool sconosciuto: {name}")
        
        return [TextContent(type="text", text=result)]
    
    except Exception as e:
        logger.error(f"Errore in {name}: {e}")
        error_response = json.dumps({"error": str(e)}, ensure_ascii=False)
        return [TextContent(type="text", text=error_response)]

async def main():
    """Funzione principale per avviare il server"""
    # Testa connessione prima di avviare
    if not test_connection():
        logger.error("❌ Server non avviato - problemi di connessione al database")
        return
    
    # Solo modalità stdio
    logger.info("🚀 Avvio server MCP in modalità stdio...")
    logger.info("💡 Per OpenWebUI usa: mcpo --port 8001 -- python server.py")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, 
            write_stream, 
            InitializationOptions(
                server_name="booking-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    tools=ToolsCapability()
                )
            )
        )

def test_stdio():
    """Test per verificare che stdio funzioni"""
    import sys
    logger.info("📝 Test stdio...")
    logger.info("✅ Logging funziona")

if __name__ == "__main__":
    test_stdio()
    asyncio.run(main())