import json
import requests
import logging
import os
import base64
from typing import Dict, Any, Optional
from datetime import datetime
from database import get_db_connection, convert_decimals

class ActivityManager:
    """Gestore delle attività tramite API REST con autenticazione token"""
    
    def __init__(self):
        self.base_url = os.getenv('API_BASE_URL')
        self.username = os.getenv('API_USERNAME')
        self.password = os.getenv('API_PASSWORD')
        self.company = os.getenv('API_COMPANY')
        self.instance = os.getenv('API_INSTANCE')
        self.current_token = None
        self.ob_code = os.getenv('API_OB_CODE')
        self.application_id = os.getenv('API_APPLICATION_ID', '00002')
        self.task_entity_name = os.getenv('API_TASK_ENTITY_NAME') # 'EV_TASK'
        self.task_action_name = os.getenv('API_TASK_ACTION_NAME') # 'Add_EV_TASK'
        self.task_bo_name = os.getenv('API_TASK_BO_NAME') # 'BO_EV_TASK'

        # Tipi di task corrispondenti ai tipi di risorsa
        self.task_type_rooms = os.getenv('TASK_TYPE_ROOMS')
        self.task_type_vehicles = os.getenv('TASK_TYPE_VEHICLES') 
        self.task_type_projectors = os.getenv('TASK_TYPE_PROJECTORS')

        # Validazione delle variabili d'ambiente
        required_vars = [
            'API_BASE_URL', 'API_USERNAME', 'API_PASSWORD', 'API_COMPANY', 
            'API_INSTANCE', 'API_OB_CODE', 'RESOURCE_TYPE_ROOMS', 
            'RESOURCE_TYPE_VEHICLES', 'RESOURCE_TYPE_PROJECTORS',
            'TASK_TYPE_ROOMS', 'TASK_TYPE_VEHICLES', 'TASK_TYPE_PROJECTORS'
        ]
        for var in required_vars:
            if not os.getenv(var):
                raise ValueError(f"Variabile d'ambiente mancante: {var}")

        # Mapping dinamico tipo risorsa -> tipo task
        self.TASK_TYPE_MAPPING = {
            os.getenv('RESOURCE_TYPE_ROOMS'): self.task_type_rooms,
            os.getenv('RESOURCE_TYPE_VEHICLES'): self.task_type_vehicles,
            os.getenv('RESOURCE_TYPE_PROJECTORS'): self.task_type_projectors,
        }
        
        
    def get_next_task_id(self) -> Optional[int]:
        """Ottiene il prossimo ID task progressivo dal database"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT c.autonum FROM cpwarn c WHERE c.tablecode = %s", ('prog\\taskevents',))
            result = cursor.fetchone()

            cursor.close()
            conn.close()

            if result and result['autonum'] is not None:
                current_id = convert_decimals(result['autonum'])
                return int(current_id) + 1
                 
        except Exception as e:
            logger.error(f"Errore nel recupero task_id: {e}")
            return None

    def get_resource_info(self, resource_id: str) -> Dict[str, Any]:
        """Ottiene informazioni sulla risorsa e determina il tipo task"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT reresourceid, redescri, retype, flactive
                FROM resources 
                WHERE reresourceid = %s AND flactive = 1
            """, (resource_id,))
            
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                retype = result['retype']
                task_type = self.TASK_TYPE_MAPPING.get(retype)
                ob_code = self.ob_code
                
                return {
                    "found": True,
                    "resource_id": result['reresourceid'],
                    "resource_type": retype,
                    "task_type": task_type,
                    "ob_code": ob_code
                }
            else:
                return {
                    "found": False,
                    "error": f"Risorsa '{resource_id}' non trovata o non attiva"
                }
                
        except Exception as e:
            return {
                "found": False,
                "error": f"Errore nel recupero informazioni risorsa: {str(e)}"
            }
    
    def get_token(self) -> Optional[str]:
        """Richiede un token di autenticazione al server"""
        try:
            url = f"{self.base_url}/getToken"
            params = {
                "username": self.username,
                "password": self.password,
                "company": self.company,
                "instance": self.instance
            }
            
            response = requests.post(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("responseStatus", {}).get("code") == "200":
                token = data.get("responseData", {}).get("result")
                if token:
                    self.current_token = token
                    return token
            return None
                
        except Exception:
            return None
    
    def release_token(self) -> bool:
        """Rilascia il token corrente"""
        if not self.current_token:
            return True
            
        try:
            url = f"{self.base_url}/releaseToken"
            headers = {
                "Authorization": self.current_token,
                "Content-Type": "application/json"
            }
            
            response = requests.post(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            self.current_token = None
            return True
            
        except Exception:
            return False
    
    def create_activity_xml(self, title: str, resource_ids: list, start_time: str, end_time: str, task_id: Optional[int] = None) -> Optional[str]:
        """Crea l'XML per una nuova attività o per aggiornare un'attività esistente"""
        try:
            # Se task_id non è fornito, genera un nuovo ID
            if task_id is None:
                task_id = self.get_next_task_id()
                if task_id is None:
                    raise Exception("Impossibile ottenere task_id dal database")
            
            # Converte resource_ids in lista se è una stringa
            if isinstance(resource_ids, str):
                resource_ids = [resource_ids]
            
            # Valida che ci sia almeno una risorsa
            if not resource_ids:
                raise Exception("Deve essere specificata almeno una risorsa")
            
            # Ottieni informazioni per tutte le risorse
            resources_info = []
            for resource_id in resource_ids:
                resource_info = self.get_resource_info(resource_id)
                if not resource_info["found"]:
                    raise Exception(resource_info["error"])
                resources_info.append(resource_info)
            
            # Valida e formatta le date
            try:
                start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
                end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
            except ValueError:
                raise ValueError("Formato data deve essere YYYY-MM-DD HH:MM")
            
            # Formatta date e orari per l'XML
            dt_begin = start_dt.strftime('%Y-%m-%d')
            dt_end = end_dt.strftime('%Y-%m-%d')
            tm_begin = start_dt.strftime('%H:%M')
            tm_end = end_dt.strftime('%H:%M')
            
            # Usa i valori della prima risorsa per i parametri generali
            first_resource = resources_info[0]
            task_type = first_resource["task_type"]
            ob_code = self.ob_code
            
            # Costruisci gli elementi risorsa
            resources_xml = ""
            for resource_info in resources_info:
                resources_xml += f'''
                                <{self.task_entity_name}_{self.ob_code}>
                                    <RLRESOURCEID_K>{self._escape_xml(resource_info["resource_id"])}</RLRESOURCEID_K>
                                    <RLRESTYPE>{resource_info["resource_type"]}</RLRESTYPE>
                                </{self.task_entity_name}_{self.ob_code}>'''
            
            xml_content = f'''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
                                <{self.task_entity_name} xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ConsolidationDate="01-01-1900" applicationId="{self.application_id}">
                                    <{self.task_action_name} TETASKID_K="{task_id}" TETITLE="{self._escape_xml(title)}" TETYPE="{task_type}" dtBegin="{dt_begin}" tmBegin="{tm_begin}" dtEnd="{dt_end}" tmEnd="{tm_end}">
                                        <{self.task_bo_name}_{self.ob_code}>{resources_xml}
                                        </{self.task_bo_name}_{self.ob_code}>
                                    </{self.task_action_name}>
                                </{self.task_entity_name}>'''
            
            return xml_content
            
        except Exception as e:
            raise Exception(f"Errore nella creazione dell'XML: {str(e)}")
    
    def _escape_xml(self, text: str) -> str:
        """Escape caratteri speciali XML"""
        if not text:
            return ""
        return (text.replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;")
                   .replace("\"", "&quot;")
                   .replace("'", "&#39;"))
    
    def create_activity(self, title: str, resource_ids, start_time: str, end_time: str) -> Dict[str, Any]:
        """Crea una nuova attività utilizzando l'API REST con una o più risorse"""
        token_obtained = False
        
        try:
            # Converte in lista se necessario
            if isinstance(resource_ids, str):
                resource_ids = [resource_ids]
            
            # Step 1: Ottieni token
            if not self.get_token():
                return {
                    "success": False,
                    "error": "Impossibile ottenere il token di autenticazione"
                }
            
            token_obtained = True
            
            # Step 2: Crea XML dell'attività
            try:
                xml_data = self.create_activity_xml(title, resource_ids, start_time, end_time)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Errore nella creazione dell'XML: {str(e)}"
                }
            
            # Step 3: Invia richiesta creazione attività
            url = f"{self.base_url}/{self.application_id}/{self.task_entity_name}"
            headers = {
                "Authorization": self.current_token,
                "Content-Type": "application/xml"
            }
            
            params = {"data": xml_data}
            
            response = requests.post(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            # Analizza la risposta
            response_data = response.json()
            status_code = response_data.get("responseStatus", {}).get("code")
            
            if status_code == "201":
                # Decodifica l'XML dal base64
                server_xml = xml_data  # fallback al nostro XML
                try:
                    result_data = response_data.get("responseData", {})
                    if result_data.get("type") == "base64Encoded" and result_data.get("result"):
                        decoded_bytes = base64.b64decode(result_data["result"])
                        server_xml = decoded_bytes.decode('utf-8')
                except Exception as e:
                    logger.warning(f"Impossibile decodificare XML dal server: {e}")
                    # Mantieni il nostro XML come fallback
                
                # Controlla se ci sono errori nell'XML del server
                if "ErrorCode=" in server_xml or "Errors:1" in server_xml:
                    # Estrai il messaggio di errore se possibile
                    error_msg = "Risorsa non disponibile o conflitto di prenotazione"
                    if "Attenzione:" in server_xml:
                        start = server_xml.find("Attenzione:")
                        if start != -1:
                            end = server_xml.find("@@@", start)
                            if end != -1:
                                error_msg = server_xml[start:end]
                    
                    return {
                        "success": False,
                        "error": error_msg,
                        "xml": server_xml
                    }
                
                return {
                    "success": True,
                    "message": "Attività creata con successo",
                    "resource_ids": resource_ids,
                    "xml": server_xml
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"Errore di rete: {str(e)}"
            }
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Risposta del server non valida: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Errore imprevisto: {str(e)}"
            }
        finally:
            # Rilascia sempre il token
            if token_obtained:
                self.release_token()


# Funzioni di utilità semplificate
def validate_activity_data(title: str, resource_id: str, start_time: str, end_time: str) -> Dict[str, Any]:
    """Valida i dati dell'attività prima della creazione"""
    errors = []
    
    # Validazione campi obbligatori
    if not title or not title.strip():
        errors.append("Il titolo è obbligatorio")
    
    if not resource_id or not resource_id.strip():
        errors.append("L'ID risorsa è obbligatorio")
    
    # Validazione formato date e orari
    try:
        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
        
        # Validazione logica temporale
        if start_dt >= end_dt:
            errors.append("La data e ora di fine deve essere successiva alla data e ora di inizio")
        
        # Validazione che non sia nel passato
        now = datetime.now()
        if start_dt < now:
            errors.append("La data e ora di inizio non può essere nel passato")
            
    except ValueError:
        errors.append("Formato data non valido. Utilizzare YYYY-MM-DD HH:MM")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def create_new_activity(title: str, resource_ids, start_time: str, end_time: str) -> Dict[str, Any]:
    """Funzione wrapper per creare una nuova attività con una o più risorse"""
    # Converte in lista se necessario
    if isinstance(resource_ids, str):
        resource_ids = [resource_ids]
    
    # Validazione preliminare per ogni risorsa
    for resource_id in resource_ids:
        validation = validate_activity_data(title, resource_id, start_time, end_time)
        if not validation["valid"]:
            return {
                "success": False,
                "error": f"Dati non validi per risorsa {resource_id}: " + ", ".join(validation["errors"])
            }
    
    manager = ActivityManager()
    return manager.create_activity(
        title=title,
        resource_ids=resource_ids,
        start_time=start_time,
        end_time=end_time
    )


logger = logging.getLogger(__name__)

# Tool MCP per creare una nuova attività/prenotazione tramite API REST
async def create_activity(
    title: str, 
    resource_id: str,  # può essere una stringa con ID separati da virgola
    start_time: str, 
    end_time: str,
    location: str = "",
    description: str = "",
    priority: int = 5
) -> str:
    """Tool MCP per creare una nuova attività/prenotazione tramite API REST"""
    try:
        # Converte resource_id in lista se contiene virgole
        if ',' in resource_id:
            resource_ids = [rid.strip() for rid in resource_id.split(',')]
        else:
            resource_ids = resource_id
        
        # Crea l'attività
        result = create_new_activity(title, resource_ids, start_time, end_time)
        
        # Costruisci risposta semplice
        if result["success"]:
            response = {
                "success": True,
                "message": "Attività creata con successo",
                "details": {
                    "title": title,
                    "resource_ids": resource_ids,
                    "start_time": start_time,
                    "end_time": end_time,
                    "location": location or str(resource_ids),
                    "xml": result["xml"]
                }
            }
        else:
            response = {
                "success": False,
                "error": result.get("error", "Errore sconosciuto"),
                "details": {
                    "title": title,
                    "resource_ids": resource_ids,
                    "start_time": start_time,
                    "end_time": end_time
                }
            }
        
        return json.dumps(response, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Errore imprevisto: {str(e)}",
            "details": {
                "title": title,
                "resource_ids": resource_ids if 'resource_ids' in locals() else resource_id,
                "start_time": start_time,
                "end_time": end_time
            }
        }, ensure_ascii=False, indent=2)

async def update_activity(
    task_id: int,
    title: str, 
    resource_id: str,
    start_time: str, 
    end_time: str,
    location: str = "",
    description: str = "",
    priority: int = 5
) -> str:
    """Tool MCP per aggiornare un'attività/prenotazione esistente tramite API REST"""
    try:
        # Converte resource_id in lista se contiene virgole
        if ',' in resource_id:
            resource_ids = [rid.strip() for rid in resource_id.split(',')]
        else:
            resource_ids = resource_id
        
        # Validazione preliminare per ogni risorsa
        for resource_id_single in resource_ids:
            validation = validate_activity_data(title, resource_id_single, start_time, end_time)
            if not validation["valid"]:
                return json.dumps({
                    "success": False,
                    "error": f"Dati non validi per risorsa {resource_id_single}: " + ", ".join(validation["errors"]),
                    "details": {
                        "task_id": task_id,
                        "title": title,
                        "resource_ids": resource_ids,
                        "start_time": start_time,
                        "end_time": end_time
                    }
                }, ensure_ascii=False, indent=2)
        
        # Istanzia il manager
        manager = ActivityManager()
        token_obtained = False
        
        # Step 1: Ottieni token
        if not manager.get_token():
            return json.dumps({
                "success": False,
                "error": "Impossibile ottenere il token di autenticazione",
                "details": {
                    "task_id": task_id,
                    "title": title,
                    "resource_ids": resource_ids,
                    "start_time": start_time,
                    "end_time": end_time
                }
            }, ensure_ascii=False, indent=2)
        
        token_obtained = True
        
        try:
            # Step 2: Crea XML dell'attività con task_id fornito
            xml_data = manager.create_activity_xml(title, resource_ids, start_time, end_time, task_id)
            
            # Step 3: Invia richiesta aggiornamento attività
            url = f"{manager.base_url}/00002/EV_TASK"
            headers = {
                "Authorization": manager.current_token,
                "Content-Type": "application/xml"
            }
            
            params = {"data": xml_data}
            
            response = requests.post(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            # Analizza la risposta
            response_data = response.json()
            status_code = response_data.get("responseStatus", {}).get("code")
            
            if status_code == "201":  # Accetta sia 200 che 201
                # Decodifica l'XML dal base64 se presente nella risposta
                server_xml = xml_data  # fallback al nostro XML
                try:
                    result_data = response_data.get("responseData", {})
                    if result_data.get("type") == "base64Encoded" and result_data.get("result"):
                        decoded_bytes = base64.b64decode(result_data["result"])
                        server_xml = decoded_bytes.decode('utf-8')
                except Exception as e:
                    logger.warning(f"Impossibile decodificare XML dal server: {e}")
                    # Mantieni il nostro XML come fallback
                
                # Controlla se ci sono errori nell'XML del server
                if "ErrorCode=" in server_xml or "Errors:1" in server_xml:
                    # Estrai il messaggio di errore se possibile
                    error_msg = "Risorsa non disponibile o conflitto di prenotazione"
                    if "Attenzione:" in server_xml:
                        start = server_xml.find("Attenzione:")
                        if start != -1:
                            end = server_xml.find("@@@", start)
                            if end != -1:
                                error_msg = server_xml[start:end]
                    
                    response_obj = {
                        "success": False,
                        "error": error_msg,
                        "details": {
                            "task_id": task_id,
                            "title": title,
                            "resource_ids": resource_ids,
                            "start_time": start_time,
                            "end_time": end_time,
                            "xml": server_xml
                        }
                    }
                else:
                    response_obj = {
                        "success": True,
                        "message": "Attività aggiornata con successo",
                        "details": {
                            "task_id": task_id,
                            "title": title,
                            "resource_ids": resource_ids,
                            "start_time": start_time,
                            "end_time": end_time,
                            "location": location or str(resource_ids),
                            "xml": server_xml
                        }
                    }
                
        except requests.exceptions.RequestException as e:
            response_obj = {
                "success": False,
                "error": f"Errore di rete: {str(e)}",
                "details": {
                    "task_id": task_id,
                    "title": title,
                    "resource_ids": resource_ids,
                    "start_time": start_time,
                    "end_time": end_time
                }
            }
            
        except json.JSONDecodeError as e:
            response_obj = {
                "success": False,
                "error": f"Risposta del server non valida: {str(e)}",
                "details": {
                    "task_id": task_id,
                    "title": title,
                    "resource_ids": resource_ids,
                    "start_time": start_time,
                    "end_time": end_time
                }
            }
            
        except Exception as e:
            response_obj = {
                "success": False,
                "error": f"Errore nella creazione dell'XML: {str(e)}",
                "details": {
                    "task_id": task_id,
                    "title": title,
                    "resource_ids": resource_ids,
                    "start_time": start_time,
                    "end_time": end_time
                }
            }
            
        finally:
            # Rilascia sempre il token
            if token_obtained:
                manager.release_token()
        
        return json.dumps(response_obj, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Errore imprevisto: {str(e)}",
            "details": {
                "task_id": task_id,
                "title": title,
                "resource_ids": resource_ids if 'resource_ids' in locals() else resource_id,
                "start_time": start_time,
                "end_time": end_time
            }
        }, ensure_ascii=False, indent=2)