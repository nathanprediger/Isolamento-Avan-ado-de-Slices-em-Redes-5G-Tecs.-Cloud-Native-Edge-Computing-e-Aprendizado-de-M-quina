#!/usr/bin/env python3
"""
Orquestrador de Testes Dinâmicos para 5G Network Slicing
=========================================================
Lê a configuração do teste, executa eventos programados (mudanças de prioridade,
pausa/resumo de tráfego) e registra tudo num event log.
"""

import yaml
import json
import time
import subprocess
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
TEST_CONFIG_PATH = os.getenv("TEST_FILE")


class TestOrchestrator:
    def __init__(self, config_file=TEST_CONFIG_PATH):
        self.config_file = config_file
        self.config = self.load_config()
        self.start_time = None
        self.event_log_file = self.config["monitoring"]["event_log_file"]
        self.setup_event_log()
        
    def load_config(self):
        """Carrega a configuração YAML."""
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"[ERRO] Falha ao carregar {self.config_file}: {e}")
            sys.exit(1)
    
    def setup_event_log(self):
        """Cria o arquivo de log de eventos com cabeçalho."""
        Path(self.config["monitoring"]["csv_output_dir"]).mkdir(parents=True, exist_ok=True)
        log_path = f"{self.config['monitoring']['csv_output_dir']}{self.event_log_file}"
        
        with open(log_path, 'w') as f:
            f.write("Timestamp_Offset_Seconds,Event_Type,Description,Details\n")
        
        print(f"[INIT] Event log criado em {log_path}")
    
    def log_event(self, event_type, description, details=""):
        """Registra um evento no log."""
        offset = (datetime.now() - self.start_time).total_seconds()
        log_path = f"{self.config['monitoring']['csv_output_dir']}{self.event_log_file}"
        
        safe_desc = str(description).replace('"', "'")
        safe_details = str(details).replace('"', "'")
        
        with open(log_path, 'a') as f:
            # Usa as variáveis seguras dentro das suas aspas originais
            f.write(f"{offset:.1f},{event_type},\"{safe_desc}\",\"{safe_details}\"\n")
        
        print(f"[+{offset:.1f}s] [{event_type}] {safe_desc}")
    
    def change_priority(self, changes, description=""):
        """Muda a prioridade de slices via strategist agent (com intent em linguagem natural)."""
        print(f"\n[ORCHESTRATION] Enviando intent ao strategist agent...")
        
        # O description vem do YAML e é um intent em linguagem natural
        # Ex: "Bronze recebe prioridade máxima para emergência de câmeras policiais"
        
        details = json.dumps({s: v for s, v in changes.items()})
        self.log_event("PRIORITY_CHANGE", f"Intent: {description} | Mudanças esperadas: {details}", details)
        
        print(f"\n[STRATEGIST INPUT] {description}")
        print(f"\n[!] ATENÇÃO: Cole o texto acima no chat do strategist agent:")
        print(f"    \"{description}\"")
        print(f"\nO strategist vai processar com o LLM e enviar as mudanças para os slice agents.")
        print(f"Mudanças esperadas: {', '.join([f'{s}={v}' for s, v in changes.items()])}\n")
    
    def pause_traffic(self, slice_name):
        """Pausa o tráfego de um slice matando temporariamente o container DASH."""
        try:
            namespace = "nrprediger"
            
            # Puxa o nome do pod dinamicamente direto do YAML!
            target_pod_base = self.config['slices'][slice_name]['client_pod']
            
            cmd = f"kubectl get pods -n {namespace} -o name | grep {target_pod_base}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            pods = [p.replace('pod/', '') for p in result.stdout.splitlines() if p.strip()]
            
            if not pods:
                print(f"[WARN] Nenhum pod encontrado para slice {slice_name} (buscando por {target_pod_base})")
                self.log_event("TRAFFIC_PAUSE_FAIL", f"Nenhum pod encontrado para {slice_name}", "")
                return
            
            for pod in pods:
                cmd = f'kubectl -n {namespace} exec {pod} -c dash-client -- sh -c "pkill -SIGUSR1 node" 2>/dev/null || true'
                subprocess.run(cmd, shell=True)
                print(f"[PAUSE] Tráfego pausado no pod {pod}")
            
            details = f"pods={','.join(pods)}"
            self.log_event("TRAFFIC_PAUSE", f"Tráfego pausado em {slice_name}", details)
            
        except KeyError:
            print(f"[ERROR] Slice '{slice_name}' ou 'client_pod' não definido no YAML.")
        except Exception as e:
            print(f"[ERROR] Falha ao pausar tráfego: {e}")
            self.log_event("TRAFFIC_PAUSE_ERROR", f"Erro ao pausar {slice_name}", str(e))
    
    def resume_traffic(self, slice_name):
        """Retoma o tráfego de um slice."""
        try:
            namespace = "nrprediger"
            
            # Puxa o nome do pod dinamicamente direto do YAML!
            target_pod_base = self.config['slices'][slice_name]['client_pod']
            
            cmd = f"kubectl get pods -n {namespace} -o name | grep {target_pod_base}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            pods = [p.replace('pod/', '') for p in result.stdout.splitlines() if p.strip()]
            
            if not pods:
                print(f"[WARN] Nenhum pod encontrado para slice {slice_name}")
                return
            
            for pod in pods:
                # Manda o sinal SIGUSR2 para o Node
                cmd = f'kubectl -n {namespace} exec {pod} -c dash-client -- sh -c "pkill -SIGUSR2 node" 2>/dev/null || true'
                subprocess.run(cmd, shell=True)
                print(f"[RESUME] Tráfego retomado no pod {pod}")
            
            details = f"pods={','.join(pods)}"
            self.log_event("TRAFFIC_RESUME", f"Tráfego retomado em {slice_name}", details)
            
        except KeyError:

            print(f"[ERROR] Slice '{slice_name}' ou 'client_pod' não definido no YAML.")
        except Exception as e:
            print(f"[ERROR] Falha ao retomar tráfego: {e}")
            self.log_event("TRAFFIC_RESUME_ERROR", f"Erro ao retomar {slice_name}", str(e))
    
    def run(self):
        """Executa o teste seguindo os eventos programados."""
        print("\n" + "="*70)
        print(f"INICIANDO TESTE: {self.config['test_metadata']['name']}")
        print(f"Duração: {self.config['test_metadata']['duration_seconds']}s")
        print("="*70 + "\n")
        
        self.start_time = datetime.now()
        self.log_event("TEST_START", "Teste iniciado", f"Config: {self.config_file}")
        
        try:
            if self.config['events']:
                events = sorted(self.config['events'], key=lambda e: e['timestamp'])
        
                for event in events:
                    timestamp = event['timestamp']
                    event_type = event['type']
                    description = event['description']
                    
                    # Aguarda o tempo do evento
                    while (datetime.now() - self.start_time).total_seconds() < timestamp:
                        time.sleep(1)
                    
                    # Executa o evento
                    if event_type == "priority_change":
                        self.change_priority(event['changes'], event['description'])
                    
                    elif event_type == "traffic_pause":
                        self.pause_traffic(event['pause_slice'])
                    
                    elif event_type == "traffic_resume":
                        self.resume_traffic(event['resume_slice'])   

            # Aguarda até o fim do teste
            total_duration = self.config['test_metadata']['duration_seconds']
            while (datetime.now() - self.start_time).total_seconds() < total_duration:
                time.sleep(5)
                
            self.log_event("TEST_END", "Teste finalizado", "")
            print("\n[SUCESSO] Teste concluído!")
            
        except KeyboardInterrupt:
            self.log_event("TEST_INTERRUPTED", "Teste interrompido pelo usuário", "")
            print("\n[INTERROMPIDO] Teste cancelado.")
        
        except Exception as e:
            self.log_event("TEST_ERROR", f"Erro durante execução: {e}", str(e))
            print(f"\n[ERRO] {e}")

if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else TEST_CONFIG_PATH
    orchestrator = TestOrchestrator(config_file)
    orchestrator.run()
