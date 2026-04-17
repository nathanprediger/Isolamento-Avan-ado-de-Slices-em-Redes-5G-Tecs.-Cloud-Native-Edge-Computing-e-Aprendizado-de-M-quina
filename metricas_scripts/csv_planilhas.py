import pandas as pd
import gspread
import glob
import os

# --- CONFIGURAÇÕES ---
NOME_PLANILHA = "Relatorio_Testes_5G"
ARQUIVO_CREDENCIAIS = "credentials.json"
PASTA_CSVS = "resultados/" 

def conectar_sheets():
    try:
        gc = gspread.service_account(filename=ARQUIVO_CREDENCIAIS)
        sh = gc.open(NOME_PLANILHA)
        return sh
    except Exception as e:
        print(f"[ERRO] Não foi possível conectar ao Google Sheets: {e}")
        exit(1)

def processar_planilhas():
    # Use "*.csv" se você converteu, ou "*.xlsx" se continuou com Excel.
    arquivos = glob.glob(os.path.join(PASTA_CSVS, "*.csv"))
    
    if not arquivos:
        print("[AVISO] Nenhum arquivo encontrado.")
        return None

    todos_dados = []
    
    for arquivo in arquivos:
        try:
            df = pd.read_csv(arquivo) # Mude para read_excel se for .xlsx
            nome_cenario = os.path.basename(arquivo).replace(".csv", "")
            df.insert(0, "Cenario", nome_cenario)
            todos_dados.append(df)
        except Exception as e:
            print(f" -> Erro ao ler {arquivo}: {e}")

    if todos_dados:
        return pd.concat(todos_dados, ignore_index=True)
    return None

def main():
    print("--- Processando Dados ---")
    df_bruto = processar_planilhas()
    if df_bruto is None:
        return

    colunas_para_converter = ["Bitrate Médio (kbps)", "Buffer Médio (s)", "Buffer Mín (s)"]
    
    for col in colunas_para_converter:
        if col in df_bruto.columns:
            # Transforma tudo em texto, troca vírgula por ponto, e converte para número
            # O errors='coerce' transforma lixo (ex: "N/A") em vazio (NaN), que é ignorado na média
            df_bruto[col] = df_bruto[col].astype(str).str.replace(',', '.')
            df_bruto[col] = pd.to_numeric(df_bruto[col], errors='coerce')

    # 1. MÁGICA ACONTECE AQUI: Agrupar por Cenário e calcular a Média
    # Pegamos apenas as colunas numéricas (ignorando "Cliente" e "Status")
    colunas_numericas = df_bruto.select_dtypes(include=['number']).columns.tolist()
    
    # Faz a média matemática de todos os clientes dentro de cada cenário
    df_medias = df_bruto.groupby('Cenario')[colunas_numericas].mean().reset_index()
    
    # Arredonda as médias para 2 casas decimais para ficar bonito na planilha
    df_medias = df_medias.round(2)

    print(f"Médias calculadas para {len(df_medias)} cenários.")

    # 2. Enviar para o Google Sheets
    sh = conectar_sheets()
    
    try:
        wks = sh.worksheet("Medias_Por_Cenario")
        wks.clear()
    except:
        wks = sh.add_worksheet(title="Medias_Por_Cenario", rows=100, cols=20)
    
    print("Enviando médias para a planilha...")
    wks.update([df_medias.columns.values.tolist()] + df_medias.values.tolist())

    # 3. Gerar os Gráficos Individuais
    print("Gerando Gráficos...")
    last_row = int(len(df_medias) + 1)
    sheet_id = int(wks.id)
    
    # Colunas que NÃO queremos que virem gráficos
    colunas_ignoradas = ["Cenario", "Stalls Detectados"]
    
    colunas_para_plotar = []
    for indice, nome_coluna in enumerate(df_medias.columns):
        if nome_coluna not in colunas_ignoradas:
            colunas_para_plotar.append({
                "titulo": nome_coluna,
                "col_idx": indice
            })
            
    requests_graficos = []
    linha_ancora = 1 
    
    for metrica in colunas_para_plotar:
        req_chart = {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": f"Média de {metrica['titulo']} por Teste",
                        "basicChart": {
                            "chartType": "COLUMN",
                            "legendPosition": "BOTTOM_LEGEND",
                            "headerCount": 1,
                            "domains": [
                                {
                                    "domain": {
                                        "sourceRange": {
                                            "sources": [{
                                                "sheetId": sheet_id,
                                                "startRowIndex": 0,
                                                "endRowIndex": last_row,
                                                "startColumnIndex": 0, # <--- Eixo X agora é o Cenário (Coluna A)
                                                "endColumnIndex": 1
                                            }]
                                        }
                                    }
                                }
                            ],
                            "series": [
                                {
                                    "series": {
                                        "sourceRange": {
                                            "sources": [{
                                                "sheetId": sheet_id,
                                                "startRowIndex": 0,
                                                "endRowIndex": last_row,
                                                "startColumnIndex": metrica["col_idx"],
                                                "endColumnIndex": metrica["col_idx"] + 1
                                            }]
                                        }
                                    },
                                    "targetAxis": "LEFT_AXIS"
                                }
                            ]
                        }
                    },
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {
                                "sheetId": sheet_id,
                                "rowIndex": linha_ancora,
                                "columnIndex": len(df_medias.columns) + 1 # Coloca o gráfico ao lado da tabela
                            },
                            "widthPixels": 600,
                            "heightPixels": 350
                        }
                    }
                }
            }
        }
        requests_graficos.append(req_chart)
        linha_ancora += 20 

    try:
        sh.batch_update({"requests": requests_graficos})
        print(f"Sucesso! {len(requests_graficos)} gráficos foram gerados.")
    except Exception as e:
        print(f"Erro ao gerar gráficos: {e}")

    print(f"\nPlanilha pronta: https://docs.google.com/spreadsheets/d/{sh.id}")

if __name__ == "__main__":
    main()