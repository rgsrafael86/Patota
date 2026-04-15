import streamlit as st

# --- 1. CONFIGURAÇÃO BASE ---
st.set_page_config(page_title="Patota Ajax Portal", page_icon="⚽", layout="wide", initial_sidebar_state="collapsed")

# CSS Global para a cara de SaaS, Botões e Assassino de Sidebar
st.markdown(
    """
    <style>
    [data-testid="stToolbar"] {display: none;}
    [data-testid="stSidebar"] {display: none !important;}
    [data-testid="collapsedControl"] {display: none !important;}
    .stApp { background-color: #000000; }
    h1, h2, h3, h4, h5, p, span, div { font-family: 'Helvetica', sans-serif; color: #ffffff; }
    
    /* Configuração Dark Mode Forçado para Botões */
    .stButton button {
        background-color: #121212 !important;
        border: 1px solid #8a2be2 !important;
        color: #ffffff !important;
        border-radius: 8px !important;
    }
    .stButton button:hover {
        background-color: #8a2be2 !important;
        color: #ffffff !important;
    }
    .stButton button p {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    </style>
    """, unsafe_allow_html=True
)

# --- 2. TRAVA DE SEGURANÇA (LOGIN ÚNICO) ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

def login_screen():
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        try: st.image("logo.png", use_container_width=True) 
        except: st.header("🔒 Acesso Restrito Base Ajax")
        
        st.write("### Controle de Acesso")
        senha = st.text_input("Digite a senha exclusiva da patota:", type="password")
        
        if st.button("Autenticar ⚽"):
            if senha == st.secrets.get("senha_acesso", "badenball"):
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("🚨 Senha incorreta! Entrada negada.")

# Se não estiver logado, para o script aqui e mostra o login.
if not st.session_state.logged_in:
    login_screen()
    st.stop()

# --- 3. NAVEGAÇÃO MPA ---
pg_sorteador = st.Page("pages/sorteador.py", title="Sorteador", icon="🎯", default=True)
pg_financeiro = st.Page("pages/financeiro.py", title="Financeiro", icon="💰")

# Esconde a Sidebar Nativamente (Requer Streamlit 1.36+)
pg = st.navigation([pg_sorteador, pg_financeiro], position="hidden")

# --- NAVEGAÇÃO TOP-BAR (MOBILE NATIVE) ---
st.markdown("<br>", unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1:
    if st.button("🎯 Ir para Sorteio", use_container_width=True):
        st.switch_page(pg_sorteador)
with col2:
    if st.button("💰 Ir para Financeiro", use_container_width=True):
        st.switch_page(pg_financeiro)
st.markdown("---")

# Inicia a página selecionada
pg.run()
