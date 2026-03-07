import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np

# Injeção de CSS para ocultação de elementos da interface nativa
st.markdown(
    """
    <style>
    /* Oculta a barra de ferramentas (ícone do GitHub, Share, Star, Edit) */
    [data-testid="stToolbar"] {
        display: none;
    }
    
    /* Opcional: Descomente a linha abaixo se quiser eliminar todo o cabeçalho superior */
    /* header {visibility: hidden;} */
    </style>
    """,
    unsafe_allow_html=True
)

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="PATOTA AJAX BADENBALL", page_icon="⚽", layout="wide")

# --- INÍCIO DA TRAVA DE SEGURANÇA (Copie e cole logo após o st.set_page_config) ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

def check_password():
    if st.session_state.logged_in:
        return True

    # Layout da Tela de Login
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        # Tenta carregar a logo conforme solicitado
        try:
            st.image("logo.png", use_container_width=True) 
        except:
            st.header("🔒 Acesso Restrito")
            
        st.write("### Área Exclusiva da Patota")
        senha = st.text_input("Digite a senha de acesso:", type="password")
        
        if st.button("Acessar Sistema"):
            # Verifica a senha que você configurou nos Secrets
            if senha == st.secrets["senha_acesso"]:
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Senha incorreta! Tente novamente.")
                
    return False

if not check_password():
    st.stop()  # <--- ISSO É O QUE PROTEGE SEU CÓDIGO ORIGINAL
# --- FIM DA TRAVA DE SEGURANÇA ---

# --- 2. CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #000000; }
    h1, h2, h3, h4, h5, p, span, div { font-family: 'Helvetica', sans-serif; color: #ffffff; }
    
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
        background-color: #121212;
        border: 1px solid #8a2be2;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
        text-align: center;
    }
    .player-debt { color: #ff4444; font-weight: bold; font-size: 20px; }

    @media (max-width: 768px) {
        .kpi-value { font-size: 50px !important; }
        .stImage { margin: 0 auto; }
    }
    </style>
""", unsafe_allow_html=True)

# --- 3. DADOS ---
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
        if df_f['Valor'].dtype == 'object': df_f['Valor'] = df_f['Valor'].apply(limpar_moeda)
        if df_p['Valor'].dtype == 'object': df_p['Valor'] = df_p['Valor'].apply(limpar_moeda)
        return df_f, df_p
    except: return None, None

df_fluxo, df_parametros = carregar_dados()
if df_fluxo is None: st.stop()

# --- 4. CÁLCULOS ---
def calcular_efeito_caixa(row):
    if str(row['Status']).strip().lower() != 'pago': return 0.0
    valor = abs(float(row['Valor']))
    tipo = str(row['Tipo']).strip().lower()
    if 'entrada' in tipo: return valor
    elif 'saída' in tipo or 'saida' in tipo: return -valor
    else: return 0.0

df_fluxo['Efeito_Caixa'] = df_fluxo.apply(calcular_efeito_caixa, axis=1)
saldo_atual = df_fluxo['Efeito_Caixa'].sum()

pendencias = df_fluxo[(df_fluxo['Status'] == 'Pendente') & (df_fluxo['Tipo'] == 'Entrada')]
total_pendente = pendencias['Valor'].sum()

try:
    meta_val = df_parametros[df_parametros['Parametro'] == 'Meta_Reserva']['Valor'].values[0]
    progresso_meta = min(int((saldo_atual / meta_val) * 100), 100)
except: meta_val = 800; progresso_meta = 0

# --- 5. GRÁFICO (PREPARAÇÃO) ---
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

# --- 6. VISUALIZAÇÃO ---
col_logo, col_txt = st.columns([1, 4])
with col_logo:
    try: st.image("logo.png", width=150)
    except: st.header("⚽")
with col_txt:
    st.markdown("""<div style="text-align: left; padding-top: 10px;">
        <h1 style="margin:0;">AJAX BADENBALL</h1>
        <h5 style="color: #8a2be2; margin:0;">QUINTAS-FEIRAS | 18:30</h5>
    </div>""", unsafe_allow_html=True)
st.markdown("---")

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown(f"""<div class="kpi-container"><div class="kpi-label">SALDO EM CAIXA</div><div class="kpi-value" style="color: #00d4ff;">R$ {saldo_atual:,.2f}</div></div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="kpi-container" style="border-top-color: #ff4444;"><div class="kpi-label">A RECEBER</div><div class="kpi-value" style="color: #ff4444;">R$ {total_pendente:,.2f}</div></div>""", unsafe_allow_html=True)
with c3:
    cor = "#00ff00" if progresso_meta >= 100 else "#e0e0e0"
    st.markdown(f"""<div class="kpi-container" style="border-top-color: #8a2be2;"><div class="kpi-label">META RESERVA_ +/-1 MENSALIDADE E 1 BOLA</div><div class="kpi-value" style="color: {cor};">{progresso_meta}%</div></div>""", unsafe_allow_html=True)

# Gráfico Estático
st.markdown("### 📈 EVOLUÇÃO DO CAIXA")
if not df_agrupado.empty:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_agrupado['Mes_Ref'], y=df_agrupado['Saldo_Acumulado'],
        mode='lines+markers+text', name='Saldo',
        line=dict(color='#00d4ff', width=4),
        marker=dict(size=10, color='#00d4ff'),
        text=df_agrupado['Saldo_Acumulado'].apply(lambda x: f"R$ {x:.0f}"),
        textposition="top center"
    ))
    fig.add_trace(go.Scatter(
        x=df_agrupado['Mes_Ref'], y=[meta_val]*len(df_agrupado),
        mode='lines', name='Meta',
        line=dict(color='#00ff00', width=2, dash='dash')
    ))
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='white'), height=350,
        margin=dict(l=0, r=0, t=20, b=0),
        legend=dict(orientation="h", y=1.1),
        xaxis=dict(fixedrange=True), # Trava zoom X
        yaxis=dict(fixedrange=True)  # Trava zoom Y
    )
    # CONFIGURAÇÃO DE GRÁFICO ESTÁTICO AQUI:
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
else:
    st.success("✅ Ninguém devendo!")

st.markdown("---")
with st.expander("🕵️‍♂️ AUDITORIA DOS CÁLCULOS"):
    df_audit = df_fluxo[['Mes_Ref', 'Nome', 'Tipo', 'Valor', 'Status', 'Efeito_Caixa']].copy()
    def highlight_vals(val):
        color = '#ccff33' if val > 0 else '#ff4444' if val < 0 else '#444'
        return f'color: {color}; font-weight: bold'
    st.dataframe(df_audit.style.applymap(highlight_vals, subset=['Efeito_Caixa']).format({'Valor': 'R$ {:.2f}', 'Efeito_Caixa': 'R$ {:.2f}'}), use_container_width=True)
