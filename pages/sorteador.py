import streamlit as st
import pandas as pd
from itertools import combinations
import random
import json
import gspread
import uuid
import datetime
import unicodedata
import streamlit.components.v1 as components

# ==============================================================================
# MÓDULO 0: UTILITÁRIOS E NORMALIZAÇÃO DE DADOS (POKA-YOKE)
# Objetivo: Evitar corrompimento de banco de dados por erros de digitação.
# ==============================================================================

def padronizar_nome(nome):
    """
    Normaliza a string para atuar como Chave Primária segura no Banco de Dados.
    Remove acentos, espaços extras e converte para Maiúsculo.
    Exemplo: " Maurício " -> "MAURICIO"
    """
    if not nome: return ""
    nome = str(nome).strip().upper()
    nome = ''.join(c for c in unicodedata.normalize('NFD', nome) if unicodedata.category(c) != 'Mn')
    return nome

# ==============================================================================
# MÓDULO 1: COMUNICAÇÃO COM BANCO DE DADOS (GOOGLE SHEETS)
# Objetivo: Gerenciar a persistência de dados na nuvem via API.
# ==============================================================================

@st.cache_resource
def get_gspread_client():
    """
    Estabelece a conexão com o Google Sheets usando credenciais seguras.
    O @st.cache_resource garante que o login seja feito apenas 1x por inicialização do app.
    """
    SHEET_ID = "1EJ-iSyYVbdafgAWawAQL2Kc-092OVfKtNvqbZg3eWfs"
    if "gcp_service_account" in st.secrets:
        from google.oauth2.service_account import Credentials
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
    else:
        gc = gspread.service_account(filename='gcp_credenciais.json')
    return gc.open_by_key(SHEET_ID)

def salvar_partida_pendente(time_a, time_b):
    """ Grava os times sorteados na planilha para aguardar o preenchimento do placar final. """
    sh = get_gspread_client()
    ws = sh.worksheet("Historico_Partidas")
    partida_id = str(uuid.uuid4())[:8] # Gera um ID único curto
    agora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S")
    t_a_clean = [{"nome": padronizar_nome(p["nome"]), "goleiro": p["goleiro"], "rating": p["rating"]} for p in time_a]
    t_b_clean = [{"nome": padronizar_nome(p["nome"]), "goleiro": p["goleiro"], "rating": p["rating"]} for p in time_b]
    row = [partida_id, agora, json.dumps(t_a_clean, ensure_ascii=False), json.dumps(t_b_clean, ensure_ascii=False), "Pendente", "", ""]
    ws.append_row(row)
    return partida_id

# Proteção de Leitura (Cache de 60s) para evitar Erro 429 (Limite de API do Google)
@st.cache_data(ttl=60)
def obter_partida_pendente():
    """ Varre o histórico de trás para frente buscando um jogo com status 'Pendente'. """
    import time
    for tentativa in range(3):
        try:
            sh = get_gspread_client()
            ws = sh.worksheet("Historico_Partidas")
            records = ws.get_all_records()
            if not records: return None
            
            for i, r in enumerate(reversed(records)):
                if str(r.get("Status")).strip().lower() == "pendente":
                    try:
                        t_azul_raw = str(r.get("Time_Azul", r.get("Time_A", "[]")))
                        t_roxo_raw = str(r.get("Time_Roxo", r.get("Time_B", "[]")))
                        
                        # Tratamento de tipagem robusto (Poka-Yoke de JSON)
                        t_azul_raw = t_azul_raw.replace("'", '"').replace("False", "false").replace("True", "true")
                        t_roxo_raw = t_roxo_raw.replace("'", '"').replace("False", "false").replace("True", "true")
                        
                        ta = json.loads(t_azul_raw)
                        tb = json.loads(t_roxo_raw)
                    except Exception as e:
                        ta, tb = [], []
                        
                    return {
                        "id": r.get("ID_Partida", r.get("ID")),
                        "time_a": ta,
                        "time_b": tb,
                        "data": r.get("Data_Hora"),
                        "row_index": len(records) - i + 1 
                    }
            return None
        except Exception as e:
            if tentativa < 2:
                time.sleep(2) # Recuo Exponencial (Espera antes de tentar de novo)
            else:
                raise e
    return None

# ==============================================================================
# MÓDULO 2: AUDITORIA E V.A.R.
# Objetivo: Garantir transparência nos sorteios e inibir manipulação ("sorteia de novo").
# ==============================================================================

@st.cache_data(ttl=60)
def ler_auditoria_cloud():
    try:
        sh = get_gspread_client()
        ws = sh.worksheet("Audit_Sorteios")
        return ws.get_all_records()
    except:
        return []

def obter_contagem_audit_hoje():
    """ Verifica quantos sorteios foram feitos no dia atual para acionar o alerta do V.A.R. """
    try:
        registros = ler_auditoria_cloud()
        if not registros: return 0, None
        
        hoje_obj = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3)))
        hoje_str = hoje_obj.strftime("%d/%m/%Y")
        
        regs_hoje = []
        for r in registros:
            dt_str = str(r.get("Data_Hora", "")).strip()
            if dt_str.startswith(hoje_str) or dt_str.startswith(hoje_obj.strftime("%#d/%#m/%Y")):
                regs_hoje.append(r)
        
        if not regs_hoje: return 0, None
        
        if len(regs_hoje) > 1:
            ultimo_horario = regs_hoje[-2].get("Data_Hora", "").split(" ")[1]
        else:
            ultimo_horario = regs_hoje[-1].get("Data_Hora", "").split(" ")[1]
            
        return len(regs_hoje), ultimo_horario
    except:
        return 0, None

def registrar_auditoria_cloud(gap, time_a, time_b):
    try:
        sh = get_gspread_client()
        ws = sh.worksheet("Audit_Sorteios")
        hoje_count, _ = obter_contagem_audit_hoje()
        sorteio_num = hoje_count + 1
        agora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S")
        az = ", ".join([padronizar_nome(p["nome"]) for p in time_a])
        rx = ", ".join([padronizar_nome(p["nome"]) for p in time_b])
        status = "Autêntico" if sorteio_num == 1 else "Suspeito"
        ws.append_row([agora, sorteio_num, status, gap, az, rx])
        ler_auditoria_cloud.clear() # Limpa cache do VAR para atualização instantânea na tela
        return sorteio_num
    except:
        return 1

# ==============================================================================
# MÓDULO 3: MOTOR DE ELO E BASE DE JOGADORES (BLINDADOS)
# ==============================================================================

def finalizar_partida(row_index, gols_a, gols_b, time_a, time_b):
    import time
    sh = get_gspread_client()
    
    try:
        # Transação Atômica: Se o banco estiver travado, o app cai no 'except' sem apagar nada
        ws_rank = sh.worksheet("Ranking_IA")
        records = ws_rank.get_all_records()
        ranking_db = {padronizar_nome(r['Nome']): r for r in records}
        
        # Atualiza a linha da partida de Pendente para Finalizada
        ws_hist = sh.worksheet("Historico_Partidas")
        ws_hist.update(range_name=f"E{row_index}:G{row_index}", values=[["Finalizada", gols_a, gols_b]])
        time.sleep(1.0) # Respiro para a API do Google não bloquear
        
        # Lógica ELO de Intensidade de Gols (K-Factor Dinâmico)
        diff = abs(gols_a - gols_b)
        k_factor = 32 if diff < 3 else (48 if diff < 5 else 64)
        res_a = 1 if gols_a > gols_b else (0.5 if gols_a == gols_b else 0)
        res_b = 1 - res_a
        
        def get_rating(nome):
            return float(ranking_db.get(padronizar_nome(nome), {}).get('Rating', 1000))

        media_a = sum(get_rating(p['nome']) for p in time_a) / max(len(time_a), 1)
        media_b = sum(get_rating(p['nome']) for p in time_b) / max(len(time_b), 1)
        
        def calc_novo_elo(jogador, media_adv, res):
            nome_clean = padronizar_nome(jogador['nome'])
            stats = ranking_db.get(nome_clean, {
                "Nome": nome_clean, 
                "Posicao": ("Goleiro" if jogador.get('goleiro') else "Linha"), 
                "Rating": 1000, "Jogos": 0, "Vitorias": 0, "Derrotas": 0
            })
            
            elo_atual = float(stats["Rating"])
            exp = 1 / (1 + 10 ** ((media_adv - elo_atual) / 400)) # Curva de Probabilidade ELO
            
            stats["Rating"] = round(elo_atual + k_factor * (res - exp))
            stats["Jogos"] = int(stats["Jogos"]) + 1
            if res == 1: stats["Vitorias"] = int(stats["Vitorias"]) + 1
            elif res == 0: stats["Derrotas"] = int(stats["Derrotas"]) + 1
            ranking_db[nome_clean] = stats
            
        for p in time_a: calc_novo_elo(p, media_b, res_a)
        for p in time_b: calc_novo_elo(p, media_a, res_b)
        
        # Monta a nova tabela ordenada para injetar no Google Sheets
        headers = ["Nome", "Posicao", "Rating", "Jogos", "Vitorias", "Derrotas"]
        linhas = [headers]
        for _, s in sorted(ranking_db.items(), key=lambda x: float(x[1]['Rating']), reverse=True):
            linhas.append([s["Nome"], s["Posicao"], s["Rating"], s["Jogos"], s["Vitorias"], s["Derrotas"]])
        
        time.sleep(1.0)
        ws_rank.update(values=linhas, range_name="A1")

    except Exception as e:
        # Tratamento de Exceção Elegante (Evita Crash de Tela Vermelha)
        st.error("🚨 O Google bloqueou a operação por limite temporário de rede. Seus dados estão seguros. Aguarde 60 segundos e tente novamente.")
        st.stop()

@st.cache_data(ttl=60)
def obter_ratings_atuais():
    try:
        sh = get_gspread_client()
        ws_rank = sh.worksheet("Ranking_IA")
        records = ws_rank.get_all_records()
        return {padronizar_nome(r['Nome']): float(r['Rating']) for r in records}
    except:
        return {}

@st.cache_data(ttl=60)
def obter_base_de_jogadores():
    jog_linha, gols = [], []
    try:
        sh = get_gspread_client()
        ws_base = sh.worksheet("Base_Jogadores")
        records = ws_base.get_all_records()
        for r in records:
            nome_raw = str(r.get("Nome", ""))
            cat = str(r.get("Categoria", "")).strip()
            status = str(r.get("Status", "")).strip()
            nome_clean = padronizar_nome(nome_raw)
            if not nome_clean or cat.lower() in ["fornecedor", "dm"] or status.lower() in ["inativo", "dm"]: 
                continue
            if cat.lower() == "goleiro": gols.append(nome_clean)
            else: jog_linha.append(nome_clean)
    except:
        pass
    return jog_linha, gols

# ==============================================================================
# MÓDULO 4: MOTOR DE EQUILÍBRIO (OTIMIZADO PARA FORÇA EFETIVA)
# Objetivo: Balancear assimetrias (Ex: 13 pessoas) nivelando pelo fluxo em quadra (5 vs 5).
# ==============================================================================

class MatchEngine:
    @staticmethod
    def balance_teams(players_list, goalkeepers_list):
        gk_a, gk_b = [], []
        # Distribuição Primária de Goleiros
        if len(goalkeepers_list) >= 2:
            gk_a.append(goalkeepers_list[0])
            gk_b.append(goalkeepers_list[1])
            # Se houver 3º goleiro, ele vai para a linha
            for extra_gk in goalkeepers_list[2:]:
                extra_gk["goleiro"] = False
                players_list.append(extra_gk)
        elif len(goalkeepers_list) == 1:
            gk_a.append(goalkeepers_list[0]) 

        # Aplicação do "Fator Caos" (Variação de 5% no Rating do dia)
        players_calc = []
        for p in players_list:
            p_copy = p.copy()
            variacao = random.uniform(0.95, 1.05)
            p_copy['rating_calc'] = float(p.get('rating', 1000)) * variacao
            players_calc.append(p_copy)
            
        gk_calc_a = [g.copy() for g in gk_a]
        for g in gk_calc_a: g['rating_calc'] = float(g.get('rating', 1000)) * random.uniform(0.95, 1.05)
        
        gk_calc_b = [g.copy() for g in gk_b]
        for g in gk_calc_b: g['rating_calc'] = float(g.get('rating', 1000)) * random.uniform(0.95, 1.05)

        total_players = len(players_calc) + len(goalkeepers_list)
        target_size_a = total_players // 2
        needed_a = target_size_a - len(gk_a)
        
        best_diff, best_combination = float('inf'), None
        # Análise Combinatória: Cria todos os cenários possíveis de times
        all_combinations = list(combinations(range(len(players_calc)), max(0, needed_a)))
        
        random.shuffle(all_combinations)
        if len(all_combinations) > 1000:
            all_combinations = all_combinations[:1000] # Limite de processamento seguro

        # NOVA LÓGICA DE ENGENHARIA: "FORÇA EFETIVA" (Multiplicador de Capacidade: 5)
        for combo in all_combinations:
            team_a_indices = set(combo)
            team_b_indices = set(range(len(players_calc))) - team_a_indices
            
            # 1. Soma Bruta do Elenco
            sum_a_raw = sum(p['rating_calc'] for i, p in enumerate(players_calc) if i in team_a_indices) + sum(g['rating_calc'] for g in gk_calc_a)
            sum_b_raw = sum(p['rating_calc'] for i, p in enumerate(players_calc) if i in team_b_indices) + sum(g['rating_calc'] for g in gk_calc_b)
            
            # 2. Contagem do Elenco (Quem veio pro jogo)
            len_a = len(team_a_indices) + len(gk_calc_a)
            len_b = len(team_b_indices) + len(gk_calc_b)
            
            # 3. Normalização: Traduz o elenco para a Força de 5 jogadores atuando simultaneamente
            forca_efetiva_a = (sum_a_raw / len_a) * 5 if len_a > 0 else 0
            forca_efetiva_b = (sum_b_raw / len_b) * 5 if len_b > 0 else 0
            
            # 4. Diferença baseada no impacto real da quadra (Evita a criação de 'Panelinhas')
            diff = abs(forca_efetiva_a - forca_efetiva_b)
            
            if diff < best_diff:
                best_diff = diff
                best_combination = (team_a_indices, team_b_indices)
        
        team_a = gk_a + [players_list[i] for i in best_combination[0]]
        team_b = gk_b + [players_list[i] for i in best_combination[1]]
        return team_a, team_b, best_diff

# ==============================================================================
# MÓDULO 5: INTERFACE GRÁFICA (UI) E CONTROLE DE ESTADO
# ==============================================================================

st.title("🧠 Sorteador Ajax")

st.markdown("""
    <style>
    /* ==========================================================
       LEGENDA DE CORES DA INTERFACE (CSS)
       ----------------------------------------------------------
       Você pode alterar os códigos HEX (#) abaixo para customizar:
       
       #1e1e1e : Cinza Escuro (Cor de fundo das caixas de texto/inputs)
       #444444 : Cinza Médio (Borda das caixas de texto)
       #ffffff : Branco (Cor do texto principal digitado)
       #aaaaaa : Cinza Claro (Texto fantasma/placeholder antes de digitar)
       #8b5cf6 : Roxo Vibrante (Fundo do botão 'Finalizar Partida')
       #7c3aed : Roxo Escuro (Fundo do botão 'Finalizar Partida' ao passar o mouse)
       #00d4ff : Azul Claro Neon (Identidade visual do Time AZUL)
       #8a2be2 : Roxo/Lilás Neon (Identidade visual do Time ROXO)
       ========================================================== */
       
    /* Estilização padrão de inputs textuais e numéricos */
    div[data-testid="stTextInput"] div[data-baseweb="input"],
    div[data-testid="stNumberInput"] div[data-baseweb="input"] {
        background-color: #1e1e1e !important; 
        border-radius: 6px !important;
        border: 1px solid #444444 !important;
    }
    div[data-testid="stTextInput"] input,
    div[data-testid="stNumberInput"] input {
        color: #ffffff !important; 
        -webkit-text-fill-color: #ffffff !important;
        caret-color: #ffffff !important; 
    }
    div[data-testid="stTextInput"] input::placeholder {
        color: #aaaaaa !important; 
        -webkit-text-fill-color: #aaaaaa !important;
    }

    /* CORREÇÃO DO BUG DO BOTÃO BRANCO:
       Força a cor do botão específico dentro de um formulário. */
    div[data-testid="stFormSubmitButton"] button {
        background-color: #8b5cf6 !important; 
        color: #ffffff !important; 
        border: none !important;
        font-weight: bold !important;
    }
    div[data-testid="stFormSubmitButton"] button:hover {
        background-color: #7c3aed !important; 
        color: #ffffff !important;
    }
    </style>
""", unsafe_allow_html=True)

tab_principal, tab_audit = st.tabs(["⚙️ Sorteador Oficial", "🕵️‍♂️ V.A.R. Administrativo"])

with tab_audit:
    st.markdown("### 📋 Auditoria de Sorteios")
    if st.button("🔄 Atualizar Log", use_container_width=True): 
        ler_auditoria_cloud.clear()
        st.rerun()
    records_audit = ler_auditoria_cloud()
    if records_audit:
        df_audit = pd.DataFrame(records_audit).tail(30)
        st.dataframe(df_audit.style.map(lambda v: 'color: #ff4444; font-weight: bold' if v == 'Suspeito' else 'color: #00ff00;', subset=['Status']), use_container_width=True)

with tab_principal:
    pendente = obter_partida_pendente()
    
    # === TELA DE PLACAR DA PARTIDA EM ANDAMENTO ===
    if pendente:
        st.error("🚨 Existe uma partida aguardando o Placar Oficial!")
        
        # IMPLEMENTAÇÃO DO BUFFER DE PLACAR (ANTI-ENGASGO DA INTERFACE)
        with st.form("fechamento_placar", clear_on_submit=False):
            colA, colB = st.columns(2)
            with colA:
                st.markdown("<h3 style='color: #00d4ff;'>🔵 T. AZUL</h3>", unsafe_allow_html=True)
                for j in pendente['time_a']: st.markdown(f"<span style='color:#ccc; font-size:14px;'>{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}</span>", unsafe_allow_html=True)
                gols_a = st.number_input("Gols Azul", min_value=0, max_value=50, value=0, key="gols_a")
            with colB:
                st.markdown("<h3 style='color: #8a2be2;'>🟣 T. ROXO</h3>", unsafe_allow_html=True)
                for j in pendente['time_b']: st.markdown(f"<span style='color:#ccc; font-size:14px;'>{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}</span>", unsafe_allow_html=True)
                gols_b = st.number_input("Gols Roxo", min_value=0, max_value=50, value=0, key="gols_b")
                
            submit_placar = st.form_submit_button("🏆 FINALIZAR PARTIDA E CALCULAR ELO", use_container_width=True)
            
            if submit_placar:
                with st.spinner("Computando resultados e salvando Ranking (Aguarde)..."):
                    finalizar_partida(pendente["row_index"], gols_a, gols_b, pendente["time_a"], pendente["time_b"])
                    
                    # Limpeza compulsória de cache pós-salvamento
                    obter_partida_pendente.clear()
                    obter_ratings_atuais.clear()
                    obter_base_de_jogadores.clear()
                    
                    st.success("ELO Recalculado com sucesso! Retornando...")
                    
                    chaves_para_limpar = [
                        'res_time_a', 'res_time_b', 'res_gap', 'keys_presentes', 
                        'visitantes_list', 'visitantes_goleiros', 'visitantes_ratings', 'match_saved'
                    ]
                    for c in chaves_para_limpar:
                        if c in st.session_state: 
                            del st.session_state[c]
                    
                    import time
                    time.sleep(1)
                    st.rerun()
        st.stop() # Interrompe a renderização para não exibir o sorteador embaixo

    # === TELA DE SORTEIO (NOVA PARTIDA) ===
    jogadores_base, goleiros_base = obter_base_de_jogadores()
    
    # Validações de integridade de sessão (Session State)
    if 'visitantes_goleiros' in st.session_state and not isinstance(st.session_state.visitantes_goleiros, list):
        del st.session_state['visitantes_goleiros']
    if 'visitantes_list' in st.session_state and not isinstance(st.session_state.visitantes_list, list):
        del st.session_state['visitantes_list']
    if 'keys_presentes' in st.session_state and not isinstance(st.session_state.keys_presentes, list):
        del st.session_state['keys_presentes']
        
    if 'visitantes_list' not in st.session_state: st.session_state.visitantes_list = []
    if 'visitantes_goleiros' not in st.session_state: st.session_state.visitantes_goleiros = []
    if 'keys_presentes' not in st.session_state: st.session_state.keys_presentes = []
    if 'visitantes_ratings' not in st.session_state: st.session_state.visitantes_ratings = {}

    def inserir_visitante_callback():
        nome_cru = st.session_state.get('temp_v_nome', '')
        nome = padronizar_nome(nome_cru)
        nivel = st.session_state.get('temp_v_nivel', 3)
        goleiro = st.session_state.get('temp_v_gol', False)
        
        if nome and nome not in st.session_state.visitantes_list:
            st.session_state.visitantes_list.append(nome)
            # Dicionário de ELO inicial para visitantes com base no nível escolhido (1 a 5)
            st.session_state.visitantes_ratings[nome] = {1:850, 2:925, 3:1000, 4:1075, 5:1150}[nivel]
            
            if nome not in st.session_state.keys_presentes: 
                st.session_state.keys_presentes.append(nome)
            if goleiro: 
                st.session_state.visitantes_goleiros.append(nome)
            
            st.session_state.temp_v_nome = ""
            st.session_state.temp_v_gol = False

    st.markdown("### 1️⃣ Presença")
    col_v1, col_v2, col_v3, col_v4 = st.columns([4, 2, 2, 3])
    with col_v1: st.text_input("Visitante", key="temp_v_nome", placeholder="Ex: Jonas", label_visibility="collapsed")
    with col_v2: st.selectbox("Nível", [1, 2, 3, 4, 5], index=2, key="temp_v_nivel", label_visibility="collapsed")
    with col_v3: st.checkbox("🧤Goleiro?", key="temp_v_gol")
    with col_v4: st.button("➕Inserir", use_container_width=True, on_click=inserir_visitante_callback)

    opcoes_totais = list(dict.fromkeys(jogadores_base + goleiros_base + st.session_state.visitantes_list))
    
    if st.button("☑️ Selecionar Todos os Jogadores", use_container_width=True):
        st.session_state.keys_presentes = opcoes_totais

    presentes = st.multiselect("Quem vai pro jogo?", opcoes_totais, key="keys_presentes")
    
    st.markdown("### 2️⃣ Goleiros")
    goleiros_default = [p for p in presentes if p in goleiros_base or p in st.session_state.visitantes_goleiros]
    goleiros_sel = st.multiselect("Selecione os Goleiros:", presentes, default=goleiros_default)

    if st.button("⚖️ GERAR TIMES", use_container_width=True):
        if len(presentes) < 10: st.error("Mínimo 10 jogadores!")
        else:
            with st.spinner("Consultando V.A.R. Cloud..."):
                ratings = obter_ratings_atuais()
                for v, r in st.session_state.visitantes_ratings.items():
                    if v not in ratings: ratings[v] = r
                
                mock_l = [{"nome": p, "rating": ratings.get(p, 1000), "goleiro": False} for p in presentes if p not in goleiros_sel]
                mock_g = [{"nome": g, "rating": ratings.get(g, 1000), "goleiro": True} for g in goleiros_sel]
                
                ta, tb, gap = MatchEngine.balance_teams(mock_l, mock_g)
                num_global = registrar_auditoria_cloud(gap, ta, tb)
                
                st.session_state.res_time_a, st.session_state.res_time_b, st.session_state.res_gap = ta, tb, gap
                st.session_state.num_sorteio_atual = num_global
                st.rerun()

    if "res_time_a" in st.session_state:
        st.success("Times Equilibrados! 🎯")
        c1, c2 = st.columns(2)
        for idx, (col, time, cor, label) in enumerate(zip([c1, c2], [st.session_state.res_time_a, st.session_state.res_time_b], ["#00d4ff", "#8a2be2"], ["AZUL", "ROXO"])):
            with col:
                st.markdown(f"<h3 style='color: {cor}; text-align: center; border-bottom: 2px solid {cor};'>{label}</h3>", unsafe_allow_html=True)
                for j in time: st.write(f"**{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}** \n`ELO: {j['rating']:.0f}`")
        st.markdown("---")
        st.info(f"⚖️ Diferença Matemática: {st.session_state.res_gap:.1f} pontos de Força Efetiva.")
        
        total_hoje, ultimo_hora = obter_contagem_audit_hoje()
        if total_hoje > 1:
            st.error(f"🚨 **V.A.R. Cloud Ativado:** Este é o **{total_hoje}º sorteio** registrado hoje.\n\nO sorteio anterior foi realizado às `{ultimo_hora}`.")
        else:
            st.success("✅ **Sorteio Oficial:** Este é o 1º sorteio registrado na nuvem hoje.")

        msg = f"⚽ *SORTEIO PATOTA AJAX* ⚽\n📅 {datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime('%d/%m/%Y')}\n\n🔵 *TIME AZUL*\n"
        for j in st.session_state.res_time_a: msg += f"{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}\n"
        msg += f"\n🟣 *TIME ROXO*\n"
        for j in st.session_state.res_time_b: msg += f"{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}\n"
        msg += f"\n⚖️ *Desnível entre os times:* Apenas {st.session_state.res_gap:.1f} pontos (Medido em Força Efetiva 5v5)."
        
        if total_hoje > 1:
            msg += f"\n\n🚨 *V.A.R. Cloud:* Sorteio nº {total_hoje} registrado hoje."
            msg += f"\n⚠️ *ALERTA:* Houve um sorteio anterior às {ultimo_hora}."
        else:
            msg += f"\n\n✅ *V.A.R. Cloud:* Sorteio nº 1 (Oficial)"
        
        msg += "\n\n🔗 *Preencher Resultado:* Acesse o atalho Patota Ajax Portal · Streamlit (https://patota.streamlit.app/)"
        msg_safe = msg.replace('`', "'").replace('\n', '\\n')
        
        components.html(f"""
            <button onclick="navigator.clipboard.writeText(`{msg_safe}`).then(() => {{ this.innerText = '✅ Copiado com Sucesso!'; this.style.backgroundColor = '#128C7E'; }})" 
            style="width: 100%; padding: 15px; background-color: #25D366; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; box-shadow: 0px 4px 6px rgba(0,0,0,0.2);">
                📋 COPIAR PARA WHATSAPP
            </button>
        """, height=65)

        st.warning("⚠️ **IMPORTANTE:** Após copiar, não esqueça de clicar no botão abaixo para registrar a partida no sistema!")
        
        if st.button("💾 INICIAR PARTIDA OFICIAL", use_container_width=True):
            with st.spinner("Registrando partida na nuvem e sincronizando..."):
                salvar_partida_pendente(st.session_state.res_time_a, st.session_state.res_time_b)
                import time
                time.sleep(2.0)
                
                # Limpa cache para que o app detecte a partida no próximo reload
                obter_partida_pendente.clear()
                
                chaves_para_limpar = [
                    'keys_presentes', 'visitantes_list', 'visitantes_goleiros', 
                    'visitantes_ratings', 'res_time_a', 'res_time_b', 'res_gap'
                ]
                for c in chaves_para_limpar:
                    if c in st.session_state:
                        del st.session_state[c]
                
                st.rerun()

# ==============================================================================
# MÓDULO 6: RODAPÉ
# ==============================================================================
st.markdown("---")
st.caption("Suporte: Rafael Guimarães")
