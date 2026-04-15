import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np

# Estilos específicos da página financeira
st.markdown("""
    <style>
    .kpi-container {
        background: linear-gradient(180deg, #1a1a1a 0%, #000000 100%);
        border: 1px solid #333;
        border-top: 4px solid #00d4ff;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        box-shadow: 0 0 15px rgba(0, 212, 255, 0.2);
        margin-bottom: 20px;
    }
    .kpi-label { color: #888; font-size: 14px; text-transform: uppercase; margin-bottom: 5px; }
    .kpi-value { color: #ffffff; font-weight: 900; font-size: 40px; }
    .player-card {
        background-color: #121212; border: 1px solid #8a2be2;
        border-radius: 10px; padding: 15px; margin-bottom: 10px; text-align: center;
    }
    .player-debt { color: #ff4444; font-weight: bold; font-size: 20px; }
    </style>
""", unsafe_allow_html=True)

# Lógica de Limpeza e Preparação Original
def limpar_moeda(valor):
    if isinstance(valor, str):
        limpo = valor.replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
        try: return float(limpo)
        except: return 0.0
    return valor

@st.cache_data(ttl=5)
def carregar_dados():
    url_fluxo = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTp9Eoyr5oJkOhw-7GElhvo2p8h73J_kbsee2JjUDjPNO18Lv7pv5oU3w7SC9d_II2WVRB_E4TUd1XK/pub?gid=1108345129&single=true&output=csv"
    url_param = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTp9Eoyr5oJkOhw-7GElhvo2p8h73J_kbsee2JjUDjPNO18Lv7pv5oU3w7SC9d_II2WVRB_E4TUd1XK/pub?gid=972176032&single=true&output=csv"
    
    try:
        df_f = pd.read_csv(url_fluxo)
        df_p = pd.read_csv(url_param)
        # Limpa string moeda e converte para float (errors='coerce' transforma lixo em NaN)
        df_f['Valor'] = df_f['Valor'].apply(limpar_moeda)
        df_f['Valor'] = pd.to_numeric(df_f['Valor'], errors='coerce').fillna(0.0)
        df_p['Valor'] = df_p['Valor'].apply(limpar_moeda)
        df_p['Valor'] = pd.to_numeric(df_p['Valor'], errors='coerce').fillna(0.0)
        return df_f, df_p
    except: return None, None

df_fluxo, df_parametros = carregar_dados()
if df_fluxo is None: st.stop()

# --- CÁLCULOS ROBUSTOS ---
def calcular_efeito_caixa(row):
    try:
        if str(row['Status']).strip().lower() != 'pago': 
            return 0.0
        
        val_bruto = row['Valor']
        if pd.isna(val_bruto) or str(val_bruto).strip() == "":
            return 0.0
            
        if isinstance(val_bruto, str):
            val_bruto = val_bruto.replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
            
        valor = abs(float(val_bruto))
        tipo = str(row['Tipo']).strip().lower()
        
        if 'entrada' in tipo: return valor
        elif 'saída' in tipo or 'saida' in tipo: return -valor
        else: return 0.0
    except Exception:
        return 0.0

df_fluxo['Efeito_Caixa'] = df_fluxo.apply(calcular_efeito_caixa, axis=1)
saldo_atual = df_fluxo['Efeito_Caixa'].sum()

pendencias = df_fluxo[(df_fluxo['Status'] == 'Pendente') & (df_fluxo['Tipo'] == 'Entrada')]
total_pendente = float(pd.to_numeric(pendencias['Valor'], errors='coerce').fillna(0).sum())

try:
    meta_val = df_parametros[df_parametros['Parametro'] == 'Meta_Reserva']['Valor'].values[0]
    progresso_meta = min(int((saldo_atual / meta_val) * 100), 100)
except: meta_val = 800; progresso_meta = 0

# --- GRÁFICO (PREPARAÇÃO) ---
meses_ordem = {
    'Janeiro': 1, 'Fevereiro': 2, 'Março': 3, 'Abril': 4, 'Maio': 5, 'Junho': 6,
    'Julho': 7, 'Agosto': 8, 'Setembro': 9, 'Outubro': 10, 'Novembro': 11, 'Dezembro': 12,
    'Jan': 1, 'Fev': 2, 'Mar': 3, 'Abr': 4, 'Mai': 5, 'Jun': 6,
    'Jul': 7, 'Ago': 8, 'Set': 9, 'Out': 10, 'Nov': 11, 'Dez': 12
}
def get_mes_num(m):
    try: return meses_ordem.get(m.split('/')[0].strip(), 0)
    except: return 0

df_graf = df_fluxo[df_fluxo['Efeito_Caixa'] != 0].copy()
df_graf['Mes_Num'] = df_graf['Mes_Ref'].apply(get_mes_num)
df_agrupado = df_graf.groupby(['Mes_Ref', 'Mes_Num'])['Efeito_Caixa'].sum().reset_index()
df_agrupado = df_agrupado.sort_values('Mes_Num')
df_agrupado['Saldo_Acumulado'] = df_agrupado['Efeito_Caixa'].cumsum()

# --- VISUALIZAÇÃO ---
col_logo, col_txt = st.columns([1, 4])
with col_logo:
    try: st.image("logo.png", width=150)
    except: st.header("⚽")
with col_txt:
    st.markdown("""<div style="text-align: left; padding-top: 10px;">
        <h1 style="margin:0;">AJAX BADENBALL</h1>
        <h5 style="color: #8a2be2; margin:0;">QUINTAS-FEIRAS | 18:30 (Financeiro)</h5>
    </div>""", unsafe_allow_html=True)
st.markdown("---")

c1, c2, c3 = st.columns(3)
with c1: st.markdown(f"""<div class="kpi-container"><div class="kpi-label">SALDO EM CAIXA</div><div class="kpi-value" style="color: #00d4ff;">R$ {saldo_atual:,.2f}</div></div>""", unsafe_allow_html=True)
with c2: st.markdown(f"""<div class="kpi-container" style="border-top-color: #ff4444;"><div class="kpi-label">A RECEBER</div><div class="kpi-value" style="color: #ff4444;">R$ {total_pendente:,.2f}</div></div>""", unsafe_allow_html=True)
with c3:
    cor = "#00ff00" if progresso_meta >= 100 else "#e0e0e0"
    st.markdown(f"""<div class="kpi-container" style="border-top-color: #8a2be2;"><div class="kpi-label">META RESERVA</div><div class="kpi-value" style="color: {cor};">{progresso_meta}%</div></div>""", unsafe_allow_html=True)

st.markdown("### 📈 EVOLUÇÃO DO CAIXA")
if not df_agrupado.empty:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_agrupado['Mes_Ref'], y=df_agrupado['Saldo_Acumulado'],
        mode='lines+markers+text', name='Saldo',
        line=dict(color='#00d4ff', width=4), marker=dict(size=10, color='#00d4ff'),
        text=df_agrupado['Saldo_Acumulado'].apply(lambda x: f"R$ {x:.0f}"), textposition="top center"
    ))
    fig.add_trace(go.Scatter(
        x=df_agrupado['Mes_Ref'], y=[meta_val]*len(df_agrupado),
        mode='lines', name='Meta', line=dict(color='#00ff00', width=2, dash='dash')
    ))
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='white'),
        height=350, margin=dict(l=0, r=0, t=20, b=0), legend=dict(orientation="h", y=1.1)
    )
    st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
else:
    st.info("Ainda não há pagamentos registrados para gerar o gráfico.")

st.markdown("---")
st.markdown("<h3 style='color: #8a2be2;'>📋 DÉBITOS EM ABERTO</h3>", unsafe_allow_html=True)
if not pendencias.empty:
    pendencias = pendencias.reset_index(drop=True)
    cols = st.columns(3)
    for i, row in pendencias.iterrows():
        with cols[i % 3]:
            st.markdown(f"""<div class="player-card"><div style="color:white; font-weight:bold;">{row['Nome']}</div><div style="color:#888; font-size:12px;">{row['Categoria']} • {row['Mes_Ref']}</div><div class="player-debt">R$ {row['Valor']:.0f}</div></div>""", unsafe_allow_html=True)
else: st.success("✅ Ninguém devendo!")

with st.expander("🕵️‍♂️ AUDITORIA DOS CÁLCULOS"):
    df_audit = df_fluxo[['Mes_Ref', 'Nome', 'Tipo', 'Valor', 'Status', 'Efeito_Caixa']].copy().iloc[::-1]
    def highlight_vals(val): return f"color: {'#ccff33' if val > 0 else '#ff4444' if val < 0 else '#444'}; font-weight: bold"
    st.dataframe(df_audit.style.applymap(highlight_vals, subset=['Efeito_Caixa']).format({'Valor': 'R$ {:.2f}', 'Efeito_Caixa': 'R$ {:.2f}'}), use_container_width=True)
