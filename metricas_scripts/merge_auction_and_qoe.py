#!/usr/bin/env python3
"""
Auction and QoE Data Correlation
=====================================
Merges auction_history.csv, test_events.csv, and qoe_timeseries.csv
to create a unified test analysis and generate graphs.
"""
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import sys
import warnings
from pathlib import Path

# Suppress seaborn visual warnings in the terminal
warnings.filterwarnings('ignore')

class DataCorrelator:
    def __init__(self, input_dir = "resultados/", output_dir="resultados/teste/"):
        self.output_dir = output_dir
        self.input_dir = input_dir
        self.auction_file = f"{input_dir}auction_history.csv"
        self.events_file = f"{input_dir}test_events.csv"
        self.timeseries_file = f"{input_dir}qoe_timeseries.csv"
        self.correlation_file = f"{output_dir}correlation_analysis.csv"
        
    def load_data(self):
        """Loads the three CSV files."""
        try:
            auction_df = pd.read_csv(self.auction_file)
            print(f"[OK] Loaded auction_history: {len(auction_df)} rows")
        except FileNotFoundError:
            print(f"[WARN] {self.auction_file} not found")
            auction_df = None
        
        try:
            events_df = pd.read_csv(self.events_file)
            print(f"[OK] Loaded test_events: {len(events_df)} rows")
        except FileNotFoundError:
            print(f"[WARN] {self.events_file} not found")
            events_df = None
        
        try:
            timeseries_df = pd.read_csv(self.timeseries_file)
            print(f"[OK] Loaded qoe_timeseries: {len(timeseries_df)} rows")
        except FileNotFoundError:
            print(f"[WARN] {self.timeseries_file} not found")
            timeseries_df = None
        
        return auction_df, events_df, timeseries_df
    
    def analyze_qoe_by_slice(self, timeseries_df):
        """Calculates QoE statistics per slice."""
        if timeseries_df is None:
            return None
        
        # Filter the DataFrame to keep only rows with Status 'OK'.
        if 'Status' in timeseries_df.columns:
            df_analise = timeseries_df[timeseries_df['Status'] == 'OK'].copy()
        else:
            df_analise = timeseries_df.copy()
        
        df_analise['Timestamp_Offset_Seconds'] = pd.to_numeric(df_analise['Timestamp_Offset_Seconds'], errors='coerce')
        df_analise['Bitrate_kbps'] = pd.to_numeric(df_analise['Bitrate_kbps'], errors='coerce')
        df_analise['Buffer_Seconds'] = pd.to_numeric(df_analise['Buffer_Seconds'], errors='coerce')

        # If there is a stall, zero out the bitrate so averages are not skewed
        is_stalled = (df_analise['Buffer_Seconds'] <= 0.5) & (df_analise['Timestamp_Offset_Seconds'] > 10.0)
        df_analise.loc[is_stalled, 'Bitrate_kbps'] = 0
        
        stats = df_analise.groupby('Slice').agg({
            'Bitrate_kbps': ['mean', 'std', 'min', 'max'],
            'Buffer_Seconds': ['mean', 'std', 'min', 'max'],
            'Quality_Switches': 'max',
            'Stalls': 'max'
        }).round(2)
        
        return stats
    
    def analyze_auction_outcomes(self, auction_df):
        """Analyzes auction outcomes per slice."""
        if auction_df is None:
            return None
        
        auction_df['Bid_Value'] = pd.to_numeric(auction_df['Bid_Value'], errors='coerce')
        auction_df['BW_Allocated'] = pd.to_numeric(auction_df['BW_Allocated'], errors='coerce')
        
        stats = auction_df.groupby('Agent').agg({
            'Result': lambda x: (x == 'WINNER').sum(),
            'Bid_Value': ['mean', 'min', 'max'],
            'BW_Allocated': ['mean', 'min', 'max']
        }).round(2)
        
        stats.columns = ['Victories', 'Avg_Bid', 'Min_Bid', 'Max_Bid', 'Avg_BW', 'Min_BW', 'Max_BW']
        return stats
    
    def create_correlation_timeline(self, auction_df, events_df, timeseries_df):
        """Creates a timeline correlating events, auctions, and QoE."""
        if timeseries_df is None:
            return None
        
        timeseries_df['Timestamp_Offset_Seconds'] = pd.to_numeric(timeseries_df['Timestamp_Offset_Seconds'], errors='coerce')
        timeseries_df['Bitrate_kbps'] = pd.to_numeric(timeseries_df['Bitrate_kbps'], errors='coerce')
        timeseries_df['Buffer_Seconds'] = pd.to_numeric(timeseries_df['Buffer_Seconds'], errors='coerce')
        
        timeseries_df['Period'] = (timeseries_df['Timestamp_Offset_Seconds'] // 30).astype(int) * 30
        
        period_stats = timeseries_df.groupby(['Period', 'Slice']).agg({
            'Bitrate_kbps': 'mean',
            'Buffer_Seconds': 'mean',
            'Quality_Switches': 'max',
            'Stalls': 'max'
        }).reset_index()
        
        if events_df is not None:
            events_df['Timestamp_Offset_Seconds'] = pd.to_numeric(events_df['Timestamp_Offset_Seconds'], errors='coerce')
            period_stats = period_stats.merge(
                events_df[['Timestamp_Offset_Seconds', 'Event_Type', 'Description']],
                left_on='Period',
                right_on='Timestamp_Offset_Seconds',
                how='left'
            )
        
        return period_stats

    def generate_graphs(self, auction_df, events_df, timeseries_df):
        """Generates graphs correlating events with auctions and QoE metrics."""
        if auction_df is None or events_df is None or timeseries_df is None:
            print("[WARN] Insufficient data to generate graphs.")
            return

        print("\n[INIT] Generating visualization graphs...")
        sns.set_theme(style="whitegrid")
        colors = {'PRIORITY_CHANGE': 'red', 'TRAFFIC_PAUSE': 'purple', 'TRAFFIC_RESUME': 'green', 'TEST_START': 'black', 'TEST_END': 'black'}

        # --- 1. AUCTION VS EVENTS GRAPH ---
        # Since the auction has full datetimes, we need to calculate the offset in seconds
        if 'Timestamp_Offset_Seconds' not in auction_df.columns:
            auction_df['Timestamp'] = pd.to_datetime(auction_df['Timestamp'])
            t0_auction = auction_df['Timestamp'].min()
            auction_df['Timestamp_Offset_Seconds'] = (auction_df['Timestamp'] - t0_auction).dt.total_seconds()
        
        fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
        
        sns.lineplot(data=auction_df, x='Timestamp_Offset_Seconds', y='Bid_Value', hue='Agent', marker='o', ax=axes[0])
        axes[0].set_title('Bid Value Over Time by Slice', fontsize=14)
        axes[0].set_ylabel('Bid Value')
        
        sns.lineplot(data=auction_df, x='Timestamp_Offset_Seconds', y='BW_Allocated', hue='Agent', marker='s', ax=axes[1])
        axes[1].set_title('Allocated Bandwidth (BW) Over Time by Slice', fontsize=14)
        axes[1].set_ylabel('BW Allocated')
        axes[1].set_xlabel('Test Time (Seconds)')
        
        # Draw vertical lines for events
        for _, row in events_df.iterrows():
            t = row['Timestamp_Offset_Seconds']
            e_type = row['Event_Type']
            if pd.isna(t): continue
            c = colors.get(e_type, 'gray')
            axes[0].axvline(t, color=c, linestyle='--', alpha=0.7)
            axes[1].axvline(t, color=c, linestyle='--', alpha=0.7)
            axes[0].text(t + 2, axes[0].get_ylim()[1] * 0.9, e_type, rotation=90, color=c, fontsize=8, verticalalignment='top')
            
        plt.tight_layout()
        auction_plot_path = f"{self.output_dir}graph_auction_events.png"
        plt.savefig(auction_plot_path)
        plt.close()
        print(f"[OK] Auction graph saved to: {auction_plot_path}")

        # --- 2. QOE VS EVENTS GRAPH ---
        qoe_df = timeseries_df.copy()
        qoe_df['Timestamp_Offset_Seconds'] = pd.to_numeric(qoe_df['Timestamp_Offset_Seconds'], errors='coerce')
        qoe_df['Bitrate_kbps'] = pd.to_numeric(qoe_df['Bitrate_kbps'], errors='coerce')
        qoe_df['Buffer_Seconds'] = pd.to_numeric(qoe_df['Buffer_Seconds'], errors='coerce')
        
        # Stall filter to visually reflect drops to zero in the network
        is_stalled = (qoe_df['Buffer_Seconds'] <= 0.5) & (qoe_df['Timestamp_Offset_Seconds'] > 10.0)
        qoe_df.loc[is_stalled, 'Bitrate_kbps'] = 0
        
        fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
        
        sns.lineplot(data=qoe_df, x='Timestamp_Offset_Seconds', y='Bitrate_kbps', hue='Slice', ax=axes[0])
        axes[0].set_title('Video Quality (Bitrate) Over Time by Slice', fontsize=14)
        axes[0].set_ylabel('Bitrate (kbps)')
        
        sns.lineplot(data=qoe_df, x='Timestamp_Offset_Seconds', y='Buffer_Seconds', hue='Slice', ax=axes[1])
        axes[1].set_title('Playback Health (Buffer) Over Time by Slice', fontsize=14)
        axes[1].set_ylabel('Buffer (Seconds)')
        axes[1].set_xlabel('Test Time (Seconds)')
        
        for _, row in events_df.iterrows():
            t = row['Timestamp_Offset_Seconds']
            e_type = row['Event_Type']
            if pd.isna(t): continue
            c = colors.get(e_type, 'gray')
            axes[0].axvline(t, color=c, linestyle='--', alpha=0.7)
            axes[1].axvline(t, color=c, linestyle='--', alpha=0.7)
            axes[0].text(t + 2, axes[0].get_ylim()[1] * 0.9, e_type, rotation=90, color=c, fontsize=8, verticalalignment='top')
            
        plt.tight_layout()
        qoe_plot_path = f"{self.output_dir}graph_qoe_events.png"
        plt.savefig(qoe_plot_path)
        plt.close()
        print(f"[OK] QoE graph saved to: {qoe_plot_path}")
    
    def generate_report(self):
        """Generates unified report and creates graphs."""
        print("\n" + "="*70)
        print("CORRELATION ANALYSIS: AUCTION + QoE")
        print("="*70)
        
        auction_df, events_df, timeseries_df = self.load_data()
        
        print("\n--- QoE STATISTICS BY SLICE ---")
        qoe_stats = self.analyze_qoe_by_slice(timeseries_df)
        if qoe_stats is not None:
            print(qoe_stats)
        
        print("\n--- AUCTION RESULTS ---")
        auction_stats = self.analyze_auction_outcomes(auction_df)
        if auction_stats is not None:
            print(auction_stats)
        
        print("\n--- CORRELATED TIMELINE ---")
        timeline = self.create_correlation_timeline(auction_df, events_df, timeseries_df)
        if timeline is not None:
            print(timeline.head(20))
            timeline.to_csv(self.correlation_file, index=False)
            print(f"\nTimeline saved to {self.correlation_file}")
            
        # <<< CALLING GRAPH CREATION HERE >>>
        self.generate_graphs(auction_df, events_df, timeseries_df)
        
        print("\n" + "="*70)
        print("Report and Graphs completed!")
        print("="*70)

if __name__ == "__main__":
    input_dir = sys.argv[1] if len(sys.argv) > 1 else "resultados/"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "resultados/teste/"
    os.makedirs(output_dir, exist_ok=True)
    correlator = DataCorrelator(input_dir, output_dir)
    correlator.generate_report()