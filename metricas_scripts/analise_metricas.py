import subprocess
import re
import pandas as pd
import numpy as np
import sys

# Configurações
NAMESPACE = "nrprediger"
POD_PREFIX = "ue-video-"
CONTAINER_NAME = "dash-client"

def get_pod_list():
    """Busca a lista de pods de vídeo no namespace."""
    try:
        cmd = ["kubectl", "get", "pods", "-n", NAMESPACE, "-o", "name"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        pods = [p.strip().replace("pod/", "") for p in result.stdout.splitlines()]
        return [p for p in pods if p.startswith(POD_PREFIX)]
    except Exception as e:
        print(f"[ERRO] Falha ao listar pods: {e}")
        sys.exit(1)

def parse_logs(pod_name):
    """Lê os logs do pod e extrai métricas."""
    try:
        cmd = ["kubectl", "logs", pod_name, "-n", NAMESPACE, "-c", CONTAINER_NAME]
        result = subprocess.run(cmd, capture_output=True, text=True)
        logs = result.stdout
    except Exception:
        return None

    data = {
        "bitrates": [],
        "buffers": [],
        "switches": 0,
        "stalls": 0,
        "frames_final": 0,
        "duration_log": 0,
        "errors": 0
    }

    # Regex para capturar a linha de status:
    # [STATUS 5s] Tempo: 15.0s | Frames: 450 | Buffer: 12.5s | Bitrate: 4500 kbps
    regex_status = r"Tempo: ([\d\.]+)s \| Frames: (\d+) \| Buffer: ([\d\.]+)s \| Bitrate: (.*)"
    
    for line in logs.splitlines():
        # Contar trocas de qualidade
        if "Qualidade alterada para indice" in line:
            data["switches"] += 1
        
        # Contar Erros
        if "ERRO PLAYER" in line:
            data["errors"] += 1

        # Processar Status
        if "[STATUS 5s]" in line:
            match = re.search(regex_status, line)
            if match:
                time, frames, buffer, bitrate_str = match.groups()
                
                # Buffer e Tempo
                buffer_val = float(buffer)
                data["buffers"].append(buffer_val)
                data["frames_final"] = int(frames)
                data["duration_log"] = float(time)

                # Detecção simples de Stall (Buffer zerado após o inicio)
                if buffer_val == 0.0 and float(time) > 10.0:
                    data["stalls"] += 1

                # Bitrate (Tratar "N/A", "Index: X" ou "4500 kbps")
                if "kbps" in bitrate_str:
                    try:
                        val = float(bitrate_str.replace("kbps", "").strip())
                        data["bitrates"].append(val)
                    except:
                        pass
                # Se estiver logando apenas "Index: X", não temos o valor numérico em kbps
                # O script ignora indexes puros para média, mas conta trocas acima.

    return data

def main():
    print(f"--- Iniciando Coleta de Métricas em '{NAMESPACE}' ---")
    pods = get_pod_list()
    csv_name = sys.argv[1] if len(sys.argv) > 1 else "resultado_teste_video.csv"
    if not pods:
        print("Nenhum pod encontrado.")
        return

    results = []

    for pod in pods:
        print(f"Processando: {pod}...")
        metrics = parse_logs(pod)
        
        if not metrics or not metrics["buffers"]:
            # Pod falhou ou não gerou logs de status
            results.append({
                "Cliente": pod,
                "Status": "Falha/Sem Dados",
                "Bitrate Médio (kbps)": 0,
                "Buffer Médio (s)": 0,
                "Trocas Qualidade": 0,
                "Stalls": 0
            })
            continue

        # Cálculos Finais
        avg_bitrate = np.mean(metrics["bitrates"]) if metrics["bitrates"] else 0
        avg_buffer = np.mean(metrics["buffers"]) if metrics["buffers"] else 0
        min_buffer = np.min(metrics["buffers"]) if metrics["buffers"] else 0
        
        results.append({
            "Cliente": pod,
            "Status": "Sucesso" if metrics["errors"] == 0 else "Com Erros",
            "Bitrate Médio (kbps)": round(avg_bitrate, 2),
            "Buffer Médio (s)": round(avg_buffer, 2),
            "Buffer Mín (s)": round(min_buffer, 2),
            "Trocas Qualidade": metrics["switches"],
            "Stalls Detectados": metrics["stalls"],
            "Frames Totais": metrics["frames_final"]
        })

    # Criar DataFrame e Exibir
    df = pd.DataFrame(results)
    
    if not df.empty:
        print("\n" + "="*80)
        print("RESUMO DE PERFORMANCE DASH (5G)")
        print("="*80)
        # Reordenar colunas
        cols = ["Cliente", "Bitrate Médio (kbps)", "Buffer Médio (s)", "Trocas Qualidade", "Stalls Detectados", "Status"]
        print(df[cols].to_string(index=False))
        
        print("\n--- Estatísticas Globais ---")
        print(f"Média Geral de Bitrate: {df['Bitrate Médio (kbps)'].mean():.2f} kbps")
        print(f"Média Geral de Buffer:  {df['Buffer Médio (s)'].mean():.2f} s")
        print(f"Total de Stalls:        {df['Stalls Detectados'].sum()}")
        
        # Salvar CSV
        df.to_csv("resultados/" + csv_name + ".csv", index=False)
        print("\nDados salvos em " + csv_name + ".csv")

if __name__ == "__main__":
    main()