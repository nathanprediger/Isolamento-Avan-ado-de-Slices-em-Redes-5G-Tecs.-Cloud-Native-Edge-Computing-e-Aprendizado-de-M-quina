#!/usr/bin/env python3
"""
Correlação de Dados de Leilão com QoE
=====================================
Mescla auction_history.csv, test_events.csv e qoe_timeseries.csv
para criar uma análise unificada do teste.
"""

import pandas as pd
import sys
from pathlib import Path

class DataCorrelator:
    def __init__(self, output_dir="resultados/"):
        self.output_dir = output_dir
        self.auction_file = f"{output_dir}auction_history.csv"
        self.events_file = f"{output_dir}test_events.csv"
        self.timeseries_file = f"{output_dir}qoe_timeseries.csv"
        self.correlation_file = f"{output_dir}correlation_analysis.csv"
        
    def load_data(self):
        """Carrega os três arquivos CSV."""
        try:
            auction_df = pd.read_csv(self.auction_file)
            print(f"[OK] Carregado auction_history: {len(auction_df)} linhas")
        except FileNotFoundError:
            print(f"[WARN] {self.auction_file} não encontrado")
            auction_df = None
        
        try:
            events_df = pd.read_csv(self.events_file)
            print(f"[OK] Carregado test_events: {len(events_df)} linhas")
        except FileNotFoundError:
            print(f"[WARN] {self.events_file} não encontrado")
            events_df = None
        
        try:
            timeseries_df = pd.read_csv(self.timeseries_file)
            print(f"[OK] Carregado qoe_timeseries: {len(timeseries_df)} linhas")
        except FileNotFoundError:
            print(f"[WARN] {self.timeseries_file} não encontrado")
            timeseries_df = None
        
        return auction_df, events_df, timeseries_df
    
    def analyze_qoe_by_slice(self, timeseries_df):
        """Calcula estatísticas de QoE por slice."""
        if timeseries_df is None:
            return None
        
        # Filtramos o DataFrame para manter apenas as linhas com Status 'OK'.
        # Isso ignora os momentos de pausa para não distorcer a média de buffer e bitrate.
        if 'Status' in timeseries_df.columns:
            df_analise = timeseries_df[timeseries_df['Status'] == 'OK'].copy()
        else:
            # Fallback caso rode com um CSV antigo que não tinha a coluna Status
            df_analise = timeseries_df.copy()
        
        # Converter colunas numéricas
        df_analise['Timestamp_Offset_Seconds'] = pd.to_numeric(df_analise['Timestamp_Offset_Seconds'], errors='coerce')
        df_analise['Bitrate_kbps'] = pd.to_numeric(df_analise['Bitrate_kbps'], errors='coerce')
        df_analise['Buffer_Seconds'] = pd.to_numeric(df_analise['Buffer_Seconds'], errors='coerce')

        is_stalled = (df_analise['Buffer_Seconds'] <= 0.5) & (df_analise['Timestamp_Offset_Seconds'] > 10.0)

        df_analise.loc[is_stalled, 'Bitrate_kbps'] = 0
        
        stats = df_analise.groupby('Slice').agg({
            'Bitrate_kbps': ['mean', 'std', 'min', 'max'],
            'Buffer_Seconds': ['mean', 'std', 'min', 'max'],
            'Quality_Switches': 'sum',
            'Stalls': 'max'
        }).round(2)
        
        return stats
    
    def analyze_auction_outcomes(self, auction_df):
        """Analisa resultados do leilão por slice."""
        if auction_df is None:
            return None
        
        # Converter colunas numéricas
        auction_df['Bid_Value'] = pd.to_numeric(auction_df['Bid_Value'], errors='coerce')
        auction_df['BW_Allocated'] = pd.to_numeric(auction_df['BW_Allocated'], errors='coerce')
        
        # Agregar por agente
        stats = auction_df.groupby('Agent').agg({
            'Result': lambda x: (x == 'WINNER').sum(),  # Contar vitórias
            'Bid_Value': ['mean', 'min', 'max'],
            'BW_Allocated': ['mean', 'min', 'max']
        }).round(2)
        
        stats.columns = ['Victories', 'Avg_Bid', 'Min_Bid', 'Max_Bid', 'Avg_BW', 'Min_BW', 'Max_BW']
        
        return stats
    
    def create_correlation_timeline(self, auction_df, events_df, timeseries_df):
        """Cria um timeline correlacionando eventos, leilões e QoE."""
        if timeseries_df is None:
            print("[WARN] Impossible to create timeline without timeseries data")
            return None
        
        timeline = []
        
        # Agregar timeseries por slice e por período (digamos, a cada 10s)
        timeseries_df['Timestamp_Offset_Seconds'] = pd.to_numeric(
            timeseries_df['Timestamp_Offset_Seconds'], errors='coerce'
        )
        timeseries_df['Bitrate_kbps'] = pd.to_numeric(timeseries_df['Bitrate_kbps'], errors='coerce')
        timeseries_df['Buffer_Seconds'] = pd.to_numeric(timeseries_df['Buffer_Seconds'], errors='coerce')
        
        timeseries_df['Period'] = (timeseries_df['Timestamp_Offset_Seconds'] // 30).astype(int) * 30
        
        period_stats = timeseries_df.groupby(['Period', 'Slice']).agg({
            'Bitrate_kbps': 'mean',
            'Buffer_Seconds': 'mean',
            'Quality_Switches': 'sum',
            'Stalls': 'sum'
        }).reset_index()
        
        # Mesclar com eventos
        if events_df is not None:
            events_df['Timestamp_Offset_Seconds'] = pd.to_numeric(
                events_df['Timestamp_Offset_Seconds'], errors='coerce'
            )
            period_stats = period_stats.merge(
                events_df[['Timestamp_Offset_Seconds', 'Event_Type', 'Description']],
                left_on='Period',
                right_on='Timestamp_Offset_Seconds',
                how='left'
            )
        
        return period_stats
    
    def generate_report(self):
        """Gera relatório unificado."""
        print("\n" + "="*70)
        print("ANÁLISE DE CORRELAÇÃO: LEILÃO + QoE")
        print("="*70)
        
        auction_df, events_df, timeseries_df = self.load_data()
        
        print("\n--- ESTATÍSTICAS DE QoE POR SLICE ---")
        qoe_stats = self.analyze_qoe_by_slice(timeseries_df)
        if qoe_stats is not None:
            print(qoe_stats)
        
        print("\n--- RESULTADOS DO LEILÃO ---")
        auction_stats = self.analyze_auction_outcomes(auction_df)
        if auction_stats is not None:
            print(auction_stats)
        
        print("\n--- TIMELINE CORRELACIONADA ---")
        timeline = self.create_correlation_timeline(auction_df, events_df, timeseries_df)
        if timeline is not None:
            print(timeline.head(20))  # Primeiras 20 linhas
            timeline.to_csv(self.correlation_file, index=False)
            print(f"\nTimeline salva em {self.correlation_file}")
        
        print("\n" + "="*70)
        print("Relatório concluído!")
        print("="*70)

if __name__ == "__main__":
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "resultados/"
    correlator = DataCorrelator(output_dir)
    correlator.generate_report()
