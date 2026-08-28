#!/usr/bin/env python3
"""
Integração com Google Sheets (QoE + Leilão + Eventos + INFRAESTRUTURA)
===============================================================
Lê todas as execuções, agrega médias de QoE, Leilão e Infraestrutura (Prometheus),
e exporta para o Google Sheets criando 8 gráficos combinados.
Inclui as descrições dos eventos na tabela de dados ao lado dos marcadores.
"""

import pandas as pd
import gspread
import glob
import os
import sys

# --- CONFIGURAÇÕES ---
NOME_PLANILHA = "Relatorio_Testes_5G_Time_Series"
ARQUIVO_CREDENCIAIS = "credentials.json"

def conectar_sheets():
    """Autentica na API do Google Sheets."""
    try:
        gc = gspread.service_account(filename=ARQUIVO_CREDENCIAIS)
        sh = gc.open(NOME_PLANILHA)
        print(f"[OK] Conectado à planilha: {NOME_PLANILHA}")
        return sh
    except Exception as e:
        print(f"[ERRO] Falha ao conectar. A planilha existe e foi partilhada com o bot? Erro: {e}")
        sys.exit(1)

def limpar_aba(sh, nome_aba):
    """Garante que a aba exista e esteja limpa."""
    try:
        wks = sh.worksheet(nome_aba)
        wks.clear()
        print(f"[INFO] Aba '{nome_aba}' limpa para novos dados.")
    except gspread.exceptions.WorksheetNotFound:
        wks = sh.add_worksheet(title=nome_aba, rows="1000", cols="40")
        print(f"[INFO] Aba '{nome_aba}' criada.")
    return wks

def gerar_grafico_combo_eventos(sheet_id, last_row, col_idx_lista, idx_col_evento, num_cols, titulo, linha_ancora):
    """Constrói o payload JSON para um gráfico COMBO (Linhas + Barras Verticais de Evento)."""
    series = []
    
    for nome_col, col_idx in col_idx_lista:
        series.append({
            "series": {
                "sourceRange": {
                    "sources": [{"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": last_row, "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1}]
                }
            },
            "targetAxis": "LEFT_AXIS",
            "type": "LINE"
        })

    if idx_col_evento is not None:
        event_series = {
            "series": {
                "sourceRange": {
                    "sources": [{"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": last_row, "startColumnIndex": idx_col_evento, "endColumnIndex": idx_col_evento + 1}]
                }
            },
            "targetAxis": "RIGHT_AXIS",
            "type": "COLUMN",
            "colorStyle": {"rgbColor": {"red": 0.85, "green": 0.85, "blue": 0.85}}
        }
        series.append(event_series)

    return {
        "addChart": {
            "chart": {
                "spec": {
                    "title": titulo,
                    "basicChart": {
                        "chartType": "COMBO",
                        "legendPosition": "BOTTOM_LEGEND",
                        "axis": [
                            {"position": "BOTTOM_AXIS", "title": "Período (Segundos)"},
                            {"position": "LEFT_AXIS", "title": "Valor da Métrica"},
                            {
                                "position": "RIGHT_AXIS", 
                                "title": "", 
                                "viewWindowOptions": {"viewWindowMin": 0, "viewWindowMax": 1.2}
                            }
                        ],
                        "domains": [{
                            "domain": {
                                "sourceRange": {
                                    "sources": [{"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": last_row, "startColumnIndex": 0, "endColumnIndex": 1}]
                                }
                            }
                        }],
                        "series": series,
                        "headerCount": 1
                    }
                },
                "position": {
                    "overlayPosition": {
                        "anchorCell": {"sheetId": sheet_id, "rowIndex": linha_ancora, "columnIndex": num_cols + 1},
                        "widthPixels": 650,
                        "heightPixels": 420
                    }
                }
            }
        }
    }

def exportar_tabela_eventos(sh, input_dir, cenario_nome):
    """Cria uma aba isolada apenas com a Tabela de Eventos."""
    print(f"\n[1/3] Processando Tabela de Eventos...")
    arq_evt = glob.glob(os.path.join(input_dir, "**", "test_events.csv"), recursive=True)
    if arq_evt:
        df_evt = pd.read_csv(arq_evt[0])
        df_evt = df_evt.fillna("") 
        
        aba_nome = f"Eventos_{cenario_nome}"
        wks = limpar_aba(sh, aba_nome)
        wks.update([df_evt.columns.values.tolist()] + df_evt.values.tolist())
        print(f"[OK] Tabela Tabela de Eventos exportada para '{aba_nome}'.")
    else:
        print("[AVISO] Arquivo test_events.csv não encontrado.")

def exportar_resumo_estatistico(sh, input_dir, cenario_nome):
    """Gera a tabela global cruzando QoE, Leilão e Infraestrutura."""
    print(f"\n[2/3] Processando Resumo Estatístico de múltiplas execuções...")
    
    # --- 1. QoE ---
    arq_qoe = glob.glob(os.path.join(input_dir, "**", "qoe_timeseries.csv"), recursive=True)
    if not arq_qoe:
        print("[ERRO] Arquivos QoE não encontrados.")
        return
        
    dfs_qoe = [pd.read_csv(f) for f in arq_qoe]
    df_qoe = pd.concat(dfs_qoe, ignore_index=True)
    if 'Status' in df_qoe.columns: df_qoe = df_qoe[df_qoe['Status'] == 'OK']
    
    df_qoe['Buffer_Seconds'] = pd.to_numeric(df_qoe['Buffer_Seconds'], errors='coerce')
    df_qoe['Timestamp_Offset_Seconds'] = pd.to_numeric(df_qoe['Timestamp_Offset_Seconds'], errors='coerce')
    df_qoe['Bitrate_kbps'] = pd.to_numeric(df_qoe['Bitrate_kbps'], errors='coerce')
    is_stalled = (df_qoe['Buffer_Seconds'] <= 0.5) & (df_qoe['Timestamp_Offset_Seconds'] > 10.0)
    df_qoe.loc[is_stalled, 'Bitrate_kbps'] = 0
    
    stats_qoe = df_qoe.groupby('Slice').agg({
        'Bitrate_kbps': ['mean', 'std'],
        'Buffer_Seconds': ['mean', 'std'],
        'Quality_Switches': 'mean',
        'Stalls': 'mean'
    }).round(2)
    stats_qoe.columns = [f"QoE_{col[0]}_{col[1]}" for col in stats_qoe.columns.values]
    
    # --- 2. LEILÃO ---
    arq_auc = glob.glob(os.path.join(input_dir, "**", "auction_history.csv"), recursive=True)
    if arq_auc:
        dfs_auc = [pd.read_csv(f) for f in arq_auc]
        df_auc = pd.concat(dfs_auc, ignore_index=True)
        df_auc['Slice'] = df_auc['Agent'].str.replace('_slice', '')
        
        stats_auc = df_auc.groupby('Slice').agg({
            'Bid_Value': ['mean'],
            'BW_Allocated': ['mean']
        }).round(2)
        stats_auc.columns = [f"Leilao_{col[0]}_{col[1]}" for col in stats_auc.columns.values]
        stats_final = pd.merge(stats_qoe, stats_auc, left_index=True, right_index=True, how='outer')
    else:
        stats_final = stats_qoe
        
    # --- 3. INFRAESTRUTURA ---
    arq_infra = glob.glob(os.path.join(input_dir, "**", "infra_timeseries.csv"), recursive=True)
    if arq_infra:
        dfs_infra = [pd.read_csv(f) for f in arq_infra]
        df_infra = pd.concat(dfs_infra, ignore_index=True)
        
        # Cria as estatísticas apenas para colunas que realmente existam no arquivo
        colunas_disponiveis = ['UPF_CPU_Cores', 'UPF_Packets_RX', 'UPF_Packets_TX', 'UPF_RX_Kbps', 'UPF_TX_Kbps', 'UE_RX_Kbps', 'UE_TX_Kbps']
        cols_metricas = [c for c in colunas_disponiveis if c in df_infra.columns]
        
        if cols_metricas:
            agg_dict = {col: ['mean', 'max'] for col in cols_metricas}
            stats_infra = df_infra.groupby('Slice').agg(agg_dict).round(3)
            stats_infra.columns = [f"Infra_{col[0]}_{col[1]}" for col in stats_infra.columns.values]
            stats_final = pd.merge(stats_final, stats_infra, left_index=True, right_index=True, how='outer')

    stats_final = stats_final.reset_index().fillna("")
    aba_nome = f"Resumo_{cenario_nome}"
    wks = limpar_aba(sh, aba_nome)
    wks.update([stats_final.columns.values.tolist()] + stats_final.values.tolist())
    print(f"[OK] Tabela Resumo atualizada com métricas de Infraestrutura!")

def exportar_dados_temporais_e_graficos(sh, input_dir, cenario_nome, duracao_teste_segundos=900):
    """Agrega evolução temporal de QoE, Leilões, INFRA e injeta os Eventos nos gráficos."""
    print(f"\n[3/3] Processando Séries Temporais para os Gráficos...")

    # CORREÇÃO: nem todas as execuções têm exatamente o mesmo número de rodadas
    # de leilão ou a mesma duração exata de coleta (algumas se estendem alguns
    # segundos além do fim nominal do teste). Sem um corte explícito, esses
    # períodos "extras" (ex.: 930s) acabam sendo calculados a partir de uma
    # amostra muito menor que o total de execuções, produzindo pontos finais
    # não representativos. Todo Period acima de duracao_teste_segundos é
    # descartado antes de qualquer agregação.
    DURACAO_TESTE_NOMINAL = duracao_teste_segundos
    
    # ==========================================
    # 1. TEMPORAL QoE
    # ==========================================
    arq_qoe = glob.glob(os.path.join(input_dir, "**", "qoe_timeseries.csv"), recursive=True)
    df_qoe = pd.concat([pd.read_csv(f) for f in arq_qoe], ignore_index=True)
    
    df_qoe['Buffer_Seconds'] = pd.to_numeric(df_qoe['Buffer_Seconds'], errors='coerce')
    df_qoe['Timestamp_Offset_Seconds'] = pd.to_numeric(df_qoe['Timestamp_Offset_Seconds'], errors='coerce')
    df_qoe['Bitrate_kbps'] = pd.to_numeric(df_qoe['Bitrate_kbps'], errors='coerce')
    
    df_qoe = df_qoe[df_qoe['Timestamp_Offset_Seconds'] <= 950]
    
    is_stalled = (df_qoe['Buffer_Seconds'] <= 0.5) & (df_qoe['Timestamp_Offset_Seconds'] > 10.0)
    df_qoe.loc[is_stalled, 'Bitrate_kbps'] = 0
    
    if 'Status' in df_qoe.columns:
        is_paused = (df_qoe['Status'] != 'OK')
        df_qoe.loc[is_paused, 'Bitrate_kbps'] = 0

    df_qoe['Period'] = (df_qoe['Timestamp_Offset_Seconds'] // 30).astype(int) * 30
    df_qoe = df_qoe[df_qoe['Period'] <= DURACAO_TESTE_NOMINAL]
    
    df_qoe_mean = df_qoe.groupby(['Period', 'Slice'])[['Bitrate_kbps', 'Buffer_Seconds']].mean().reset_index()
    pivot_bitrate = df_qoe_mean.pivot(index='Period', columns='Slice', values='Bitrate_kbps').add_suffix('_Bitrate')
    pivot_buffer = df_qoe_mean.pivot(index='Period', columns='Slice', values='Buffer_Seconds').add_suffix('_Buffer')
    df_temp_final = pd.merge(pivot_bitrate, pivot_buffer, on='Period', how='outer')

    # ==========================================
    # 2. TEMPORAL LEILÃO
    # ==========================================
    arq_auc = glob.glob(os.path.join(input_dir, "**", "auction_history.csv"), recursive=True)
    if arq_auc:
        lista_auc_formatada = []
        for f in arq_auc:
            df_a = pd.read_csv(f)
            df_a['Timestamp'] = pd.to_datetime(df_a['Timestamp'])
            df_a['Time_Diff'] = df_a['Timestamp'].diff().dt.total_seconds()
            df_a['Internal_Run_ID'] = (df_a['Time_Diff'] > 120).cumsum()
            df_a['Offset'] = df_a.groupby('Internal_Run_ID')['Timestamp'].transform(lambda x: (x - x.min()).dt.total_seconds())
            df_a = df_a[df_a['Offset'] <= 950]
            lista_auc_formatada.append(df_a)
            
        df_auc = pd.concat(lista_auc_formatada, ignore_index=True)
        df_auc['Slice'] = df_auc['Agent'].str.replace('_slice', '')

        # CORREÇÃO: usar o contador lógico de rodadas (Auction_ID) em vez do
        # Offset derivado do relógio de parede para definir o Period. O Offset
        # acumula pequenas derivas de timing ao longo de ~30 rodadas por execução
        # (rede, asyncio.sleep, chamadas ao Kubernetes), fazendo com que a última
        # rodada de cada execução caia em um bucket de 30s ligeiramente diferente
        # de execução para execução. Isso faz o período final (e, em menor grau,
        # outros períodos de borda) ser calculado a partir de uma amostra muito
        # menor que as 30 execuções, sem qualquer aviso — foi essa a causa da
        # discrepância no dado da polícia em t=900s no Cenário Cidade Inteligente.
        df_auc['Auction_ID_Norm'] = df_auc.groupby('Internal_Run_ID')['Auction_ID'].transform(lambda x: x - x.min())
        df_auc['Period'] = df_auc['Auction_ID_Norm'] * 30
        df_auc = df_auc[df_auc['Period'] <= DURACAO_TESTE_NOMINAL]

        # Expõe quantas execuções (Internal_Run_ID distintos) contribuíram para
        # cada (Period, Slice), para que qualquer colapso amostral fique visível
        # em vez de silencioso.
        df_auc_count = df_auc.groupby(['Period', 'Slice'])['Internal_Run_ID'].nunique().reset_index(name='N_Execucoes')
        n_esperado = df_auc['Internal_Run_ID'].nunique()
        periodos_incompletos = df_auc_count[df_auc_count['N_Execucoes'] < n_esperado]
        if not periodos_incompletos.empty:
            print(f"[AVISO] {len(periodos_incompletos)} combinações (Period, Slice) têm menos de {n_esperado} execuções contribuindo — ver 'N_Execucoes' abaixo:")
            print(periodos_incompletos.to_string(index=False))

        df_auc_mean = df_auc.groupby(['Period', 'Slice'])[['Bid_Value', 'BW_Allocated']].mean().reset_index()
        pivot_bid = df_auc_mean.pivot(index='Period', columns='Slice', values='Bid_Value').add_suffix('_Bid')
        pivot_bw = df_auc_mean.pivot(index='Period', columns='Slice', values='BW_Allocated').add_suffix('_BW')
        
        df_temp_final = pd.merge(df_temp_final, pd.merge(pivot_bid, pivot_bw, on='Period', how='outer'), on='Period', how='outer')

    # ==========================================
    # 3. TEMPORAL INFRAESTRUTURA
    # ==========================================
    arq_infra = glob.glob(os.path.join(input_dir, "**", "infra_timeseries.csv"), recursive=True)
    if arq_infra:
        lista_infra = []
        for f in arq_infra:
            df_i = pd.read_csv(f)
            df_i = df_i[df_i['Timestamp_Offset_Seconds'] <= 950]
            lista_infra.append(df_i)
            
        df_infra = pd.concat(lista_infra, ignore_index=True)
        df_infra['Period'] = (df_infra['Timestamp_Offset_Seconds'] // 30).astype(int) * 30
        df_infra = df_infra[df_infra['Period'] <= DURACAO_TESTE_NOMINAL]
        
        colunas_disponiveis = ['UPF_CPU_Cores', 'UPF_Packets_RX', 'UPF_Packets_TX', 'UPF_RX_Kbps', 'UPF_TX_Kbps', 'UE_RX_Kbps', 'UE_TX_Kbps']
        cols_metricas = [c for c in colunas_disponiveis if c in df_infra.columns]
        
        if cols_metricas:
            df_infra_mean = df_infra.groupby(['Period', 'Slice'])[cols_metricas].mean().reset_index()
            
            if 'UPF_CPU_Cores' in df_infra_mean:
                pivot_cpu = df_infra_mean.pivot(index='Period', columns='Slice', values='UPF_CPU_Cores').add_suffix('_UPF_CPU')
                df_temp_final = pd.merge(df_temp_final, pivot_cpu, on='Period', how='outer')
            if 'UE_RX_Kbps' in df_infra_mean:
                pivot_net = df_infra_mean.pivot(index='Period', columns='Slice', values='UE_RX_Kbps').add_suffix('_UE_RX')
                df_temp_final = pd.merge(df_temp_final, pivot_net, on='Period', how='outer')
            if 'UPF_Packets_RX' in df_infra_mean:
                pivot_pktrx = df_infra_mean.pivot(index='Period', columns='Slice', values='UPF_Packets_RX').add_suffix('_UPF_PktRX')
                df_temp_final = pd.merge(df_temp_final, pivot_pktrx, on='Period', how='outer')
            if 'UPF_Packets_TX' in df_infra_mean:
                pivot_pkttx = df_infra_mean.pivot(index='Period', columns='Slice', values='UPF_Packets_TX').add_suffix('_UPF_PktTX')
                df_temp_final = pd.merge(df_temp_final, pivot_pkttx, on='Period', how='outer')

    # ==========================================
    # 4. EXTRAÇÃO DE EVENTOS PARA MARCADORES
    # ==========================================
    arq_evt = glob.glob(os.path.join(input_dir, "**", "test_events.csv"), recursive=True)
    if arq_evt:
        df_evt = pd.read_csv(arq_evt[0])
        df_evt = df_evt[df_evt['Timestamp_Offset_Seconds'] <= 950]
        df_evt['Period'] = (df_evt['Timestamp_Offset_Seconds'] // 30).astype(int) * 30
        df_evt = df_evt[df_evt['Period'] <= DURACAO_TESTE_NOMINAL]
        df_evt['Event_Mark'] = 1 
        
        # Agrupamos pegando a marcação e juntando as Descrições em texto
        df_evt_grouped = df_evt.groupby('Period').agg({
            'Event_Mark': 'max',
            'Description': lambda x: ' | '.join(str(d) for d in x)
        }).reset_index()
        
        df_temp_final = pd.merge(df_temp_final, df_evt_grouped, on='Period', how='left')

    # ==========================================
    # 5. LIMPEZA E EXPORTAÇÃO
    # ==========================================
    df_temp_final = df_temp_final.sort_values('Period').reset_index(drop=True)
    
    # Protege a Description do fill para o texto não vazar para linhas vazias
    colunas_metricas = [c for c in df_temp_final.columns if c not in ['Event_Mark', 'Description']]
    df_temp_final[colunas_metricas] = df_temp_final[colunas_metricas].ffill().fillna(0)
    
    if 'Event_Mark' in df_temp_final.columns:
        df_temp_final['Event_Mark'] = df_temp_final['Event_Mark'].fillna(0)
    if 'Description' in df_temp_final.columns:
        df_temp_final['Description'] = df_temp_final['Description'].fillna("")
        
    aba_nome = f"Graficos_{cenario_nome}"
    wks = limpar_aba(sh, aba_nome)
    
    df_sheets = df_temp_final.copy()
    wks.update([df_sheets.columns.values.tolist()] + df_sheets.values.tolist())
    
    # ==========================================
    # 6. CONSTRUÇÃO DOS 8 GRÁFICOS
    # ==========================================
    sheet_id = int(wks.id)
    last_row = len(df_final := df_sheets) + 1
    num_cols = len(df_final.columns)
    
    idx_evt = df_final.columns.get_loc('Event_Mark') if 'Event_Mark' in df_final.columns else None
    
    col_bitrate = [(c, i) for i, c in enumerate(df_final.columns) if "Bitrate" in c]
    col_buffer  = [(c, i) for i, c in enumerate(df_final.columns) if "Buffer" in c]
    col_bid     = [(c, i) for i, c in enumerate(df_final.columns) if "Bid" in c]
    col_bw      = [(c, i) for i, c in enumerate(df_final.columns) if "BW" in c]
    col_cpu     = [(c, i) for i, c in enumerate(df_final.columns) if "UPF_CPU" in c]
    col_net     = [(c, i) for i, c in enumerate(df_final.columns) if "UE_RX" in c] 
    col_pktrx   = [(c, i) for i, c in enumerate(df_final.columns) if "UPF_PktRX" in c]
    col_pkttx   = [(c, i) for i, c in enumerate(df_final.columns) if "UPF_PktTX" in c]
    
    requests = []
    
    if col_bitrate:
        requests.append(gerar_grafico_combo_eventos(sheet_id, last_row, col_bitrate, idx_evt, num_cols, f"1. Evolução do Bitrate ({cenario_nome})", 1))
    if col_buffer:
        requests.append(gerar_grafico_combo_eventos(sheet_id, last_row, col_buffer, idx_evt, num_cols, f"2. Saúde da Reprodução (Buffer)", 23))
    if col_bid:
        requests.append(gerar_grafico_combo_eventos(sheet_id, last_row, col_bid, idx_evt, num_cols, f"3. Oferta no Leilão (Bid)", 45))
    if col_bw:
        requests.append(gerar_grafico_combo_eventos(sheet_id, last_row, col_bw, idx_evt, num_cols, f"4. Banda Alocada no Leilão (BW)", 67))
    if col_cpu:
        requests.append(gerar_grafico_combo_eventos(sheet_id, last_row, col_cpu, idx_evt, num_cols, f"5. Uso Físico de CPU da UPF (Cores)", 89))
    if col_net:
        requests.append(gerar_grafico_combo_eventos(sheet_id, last_row, col_net, idx_evt, num_cols, f"6. Tráfego Real Recebido (uesimtun0 - Kbps)", 111))
    if col_pktrx:
        requests.append(gerar_grafico_combo_eventos(sheet_id, last_row, col_pktrx, idx_evt, num_cols, f"7. UPF: Pacotes Recebidos/s (Interface slice.*)", 133))
    if col_pkttx:
        requests.append(gerar_grafico_combo_eventos(sheet_id, last_row, col_pkttx, idx_evt, num_cols, f"8. UPF: Pacotes Enviados/s (Interface slice.*)", 155))

    if requests:
        try:
            sh.batch_update({"requests": requests})
            print(f"[OK] Os Gráficos (com marcações de eventos) foram desenhados na aba '{aba_nome}'.")
        except Exception as e:
            print(f"[ERRO] Falha ao desenhar os gráficos no Sheets: {e}")

if __name__ == "__main__":
    pasta_resultados = sys.argv[1] if len(sys.argv) > 1 else "resultados/teste/"
    nome_do_cenario = sys.argv[2] if len(sys.argv) > 2 else "Resultados_Globais"
    
    print(f"=== INICIANDO EXPORTAÇÃO MASSIVA: {nome_do_cenario} ===")
    planilha = conectar_sheets()
    
    exportar_tabela_eventos(planilha, pasta_resultados, nome_do_cenario)
    exportar_resumo_estatistico(planilha, pasta_resultados, nome_do_cenario)
    exportar_dados_temporais_e_graficos(planilha, pasta_resultados, nome_do_cenario)
    
    print("=== EXPORTAÇÃO CONCLUÍDA ===")