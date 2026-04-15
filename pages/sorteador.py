import streamlit as st
import pandas as pd
from itertools import combinations
import random
import json
import gspread
import uuid
import datetime

# --- POKA YOKE: GOOGLE SHEETS CLOUD ---
@st.cache_resource
def get_gspread_client():
    SHEET_ID = "1EJ-iSyYVbdafgAWawAQL2Kc-092OVfKtNvqbZg3eWfs"
    
    if "gcp_service_account" in st.secrets:
        # PRODUÇÃO (Streamlit Cloud) — lê dos Secrets
        import json
        from google.oauth2.service_account import Credentials
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        # Corrige quebras de linha na chave privada
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
    else:
        # LOCAL — lê do arquivo JSON
        gc = gspread.service_account(filename='gcp_credenciais.json')
    
    return gc.open_by_key(SHEET_ID)

def salvar_partida_pendente(time_a, time_b):
    sh = get_gspread_client()
    ws = sh.worksheet("Historico_Partidas")
    partida_id = str(uuid.uuid4())[:8]
    agora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S")
    row = [partida_id, agora, json.dumps(time_a, ensure_ascii=False), json.dumps(time_b, ensure_ascii=False), "Pendente", "", ""]
    ws.append_row(row)
    return partida_id

def obter_partida_pendente():
    try:
        sh = get_gspread_client()
        ws = sh.worksheet("Historico_Partidas")
        records = ws.get_all_records()
        if not records: return None
        last = records[-1]
        if str(last.get("Status")).strip().lower() == "pendente":
            return {
                "id": last.get("ID_Partida"),
                "time_a": json.loads(last.get("Time_Azul")),
                "time_b": json.loads(last.get("Time_Roxo")),
                "data": last.get("Data_Hora"),
                "row_index": len(records) + 1 
            }
        return None
    except Exception as e:
        return None

def registrar_auditoria_cloud(sorteio_num, gap, time_a, time_b):
    try:
        sh = get_gspread_client()
        ws = sh.worksheet("Audit_Sorteios")
        agora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S")
        az = ", ".join([p["nome"] for p in time_a])
        rx = ", ".join([p["nome"] for p in time_b])
        status = "Autêntico" if sorteio_num == 1 else "Suspeito"
        ws.append_row([agora, sorteio_num, status, gap, az, rx])
    except:
        pass

def ler_auditoria_cloud():
    try:
        sh = get_gspread_client()
        ws = sh.worksheet("Audit_Sorteios")
        return ws.get_all_records()
    except:
        return []

def finalizar_partida(row_index, gols_a, gols_b, time_a, time_b):
    sh = get_gspread_client()
    ws_hist = sh.worksheet("Historico_Partidas")
    ws_hist.update_cell(row_index, 5, "Finalizada")
    ws_hist.update_cell(row_index, 6, gols_a)
    ws_hist.update_cell(row_index, 7, gols_b)
    
    ws_rank = sh.worksheet("Ranking_IA")
    records = ws_rank.get_all_records()
    ranking_db = {str(r['Nome']): r for r in records}
    
    diff = abs(gols_a - gols_b)
    k_factor = 32
    if diff >= 5: k_factor = 64
    elif diff >= 3: k_factor = 48
    
    res_a = 1 if gols_a > gols_b else (0.5 if gols_a == gols_b else 0)
    res_b = 1 - res_a
    
    media_a = sum(float(ranking_db.get(p['nome'], {}).get('Rating', 1000)) for p in time_a) / max(len(time_a), 1)
    media_b = sum(float(ranking_db.get(p['nome'], {}).get('Rating', 1000)) for p in time_b) / max(len(time_b), 1)
    
    def calc_novo_elo(jogador, media_adv, res):
        nome = jogador['nome']
        stats = ranking_db.get(nome, {"Nome": nome, "Posicao": ("Goleiro" if jogador.get('goleiro') else "Linha"), "Rating": 1000, "Jogos": 0, "Vitorias": 0, "Derrotas": 0})
        elo_atual = float(stats["Rating"])
        exp = 1 / (1 + 10 ** ((media_adv - elo_atual) / 400))
        stats["Rating"] = round(elo_atual + k_factor * (res - exp))
        stats["Jogos"] = int(stats["Jogos"]) + 1
        if res == 1: stats["Vitorias"] = int(stats["Vitorias"]) + 1
        elif res == 0: stats["Derrotas"] = int(stats["Derrotas"]) + 1
        ranking_db[nome] = stats
        
    for p in time_a: calc_novo_elo(p, media_b, res_a)
    for p in time_b: calc_novo_elo(p, media_a, res_b)
    
    headers = ["Nome", "Posicao", "Rating", "Jogos", "Vitorias", "Derrotas"]
    linhas = [headers]
    for _, s in sorted(ranking_db.items(), key=lambda x: float(x[1]['Rating']), reverse=True):
        linhas.append([s["Nome"], s["Posicao"], s["Rating"], s["Jogos"], s["Vitorias"], s["Derrotas"]])
    ws_rank.clear()
    ws_rank.update(values=linhas, range_name="A1")

@st.cache_data(ttl=60)
def obter_ratings_atuais():
    try:
        sh = get_gspread_client()
        ws_rank = sh.worksheet("Ranking_IA")
        records = ws_rank.get_all_records()
        return {str(r['Nome']): float(r['Rating']) for r in records}
    except:
        return {}

@st.cache_data(ttl=60)
def obter_base_de_jogadores():
    jog_linha = []
    gols = []
    try:
        sh = get_gspread_client()
        ws_base = sh.worksheet("Base_Jogadores")
        records = ws_base.get_all_records()
        
        for r in records:
            nome = str(r.get("Nome", "")).strip()
            cat = str(r.get("Categoria", "")).strip()
            status = str(r.get("Status", "")).strip()
            
            if not nome or cat.lower() == "fornecedor" or status.lower() == "inativo":
                continue
                
            nome_display = nome
            if status.lower() == "dm":
                nome_display += " (DM)"
                
            if cat.lower() == "goleiro":
                gols.append(nome_display)
            else:
                jog_linha.append(nome_display)
                
    except Exception as e:
        pass
    return jog_linha, gols

# --- MOTOR DE ELO MATEMÁTICO ---
class MatchEngine:
    @staticmethod
    def balance_teams(players_list, goalkeepers_list):
        gk_a, gk_b = [], []
        if len(goalkeepers_list) >= 2:
            gk_a.append(goalkeepers_list[0])
            gk_b.append(goalkeepers_list[1])
            for extra_gk in goalkeepers_list[2:]:
                extra_gk["goleiro"] = False
                players_list.append(extra_gk)
        elif len(goalkeepers_list) == 1:
            gk_a.append(goalkeepers_list[0]) 

        total_players = len(players_list) + len(goalkeepers_list)
        target_size_a = total_players // 2
        needed_a = target_size_a - len(gk_a)
        
        best_diff = float('inf')
        best_combination = None
        
        all_combinations = list(combinations(range(len(players_list)), max(0, needed_a)))
        if len(all_combinations) > 500:
            all_combinations = random.sample(all_combinations, 500)

        for combo in all_combinations:
            team_a_indices = set(combo)
            team_b_indices = set(range(len(players_list))) - team_a_indices
            
            sum_a = sum(float(players_list[i].get('rating', 1000)) for i in team_a_indices) + sum(float(g.get('rating', 1000)) for g in gk_a)
            sum_b = sum(float(players_list[i].get('rating', 1000)) for i in team_b_indices) + sum(float(g.get('rating', 1000)) for g in gk_b)
            
            diff = abs(sum_a - sum_b)
            if diff < best_diff:
                best_diff = diff
                best_combination = (team_a_indices, team_b_indices)
                
        team_a = gk_a + [players_list[i] for i in best_combination[0]]
        team_b = gk_b + [players_list[i] for i in best_combination[1]]
        
        return team_a, team_b, best_diff

# --- INTERFACE MOBILE FIRST ---
st.title("🧠 Sorteador Ajax")
st.write("Layout otimizado para o seu celular 📱")

# HOTFIX 1: Força contraste e visibilidade no campo de input
st.markdown("""
    <style>
    div[data-baseweb="input"] {
        background-color: #ffffff !important;
        border: 1px solid #cccccc !important;
    }
    div[data-baseweb="input"] input {
        color: #000000 !important;
        caret-color: #000000 !important;
    }
    div[data-baseweb="input"] input::placeholder {
        color: #7f8c8d !important;
    }
    </style>
""", unsafe_allow_html=True)

# ABAS NATIVAS STREAMLIT
tab_principal, tab_audit = st.tabs(["⚙️ Sorteador Oficial", "🕵️‍♂️ V.A.R. Administrativo"])

with tab_audit:
    st.markdown("### 📋 Caixa Preta do Sorteador")
    st.write("Aqui residem todas as tentativas de gerar times (impedindo que o organizador tente sortear várias vezes até cair no seu time favorito).")
    
    if st.button("🔄 Atualizar Log da Nuvem"):
        st.rerun()
        
    records_audit = ler_auditoria_cloud()
    if records_audit:
        df_audit = pd.DataFrame(records_audit).tail(30) # Puxa ultimos 30
        
        # Colorir Status
        def color_status(val):
            if val == 'Suspeito':
                return 'color: #ff4444; font-weight: bold'
            return 'color: #00ff00;'
            
        st.dataframe(df_audit.style.map(color_status, subset=['Status']), use_container_width=True)
    else:
        st.info("Nenhuma fraude ou sorteio registrado no sistema ainda.")

with tab_principal:
    # --- BLOQUEIO POKA-YOKE: PARTIDA PENDENTE ---
    pendente = obter_partida_pendente()
    if pendente:
        st.error("🚨 Existe uma partida aguardando o Placar Oficial!")
        st.markdown(f"**Sorteio Realizado em:** {pendente['data']}")
        
        colA, colB = st.columns(2)
        with colA:
            st.markdown("<h3 style='color: #00d4ff;'>🔵 T. AZUL</h3>", unsafe_allow_html=True)
            for j in pendente['time_a']:
                icon = "🧤" if j.get("goleiro") else "🏃"
                st.markdown(f"<span style='color:#ccc; font-size:14px;'>{icon} {j['nome']}</span>", unsafe_allow_html=True)
            st.write("") 
            gols_a = st.number_input("Gols do Azul", min_value=0, max_value=50, value=0, key="gols_a")
            
        with colB:
            st.markdown("<h3 style='color: #8a2be2;'>🟣 T. ROXO</h3>", unsafe_allow_html=True)
            for j in pendente['time_b']:
                icon = "🧤" if j.get("goleiro") else "🏃"
                st.markdown(f"<span style='color:#ccc; font-size:14px;'>{icon} {j['nome']}</span>", unsafe_allow_html=True)
            st.write("") 
            gols_b = st.number_input("Gols do Roxo", min_value=0, max_value=50, value=0, key="gols_b")
            
        st.markdown("---")
        if st.button("🏆 Finalizar Partida e Atualizar Patota", use_container_width=True):
            with st.spinner("Atualizando ranking mundial da Patota na Nuvem..."):
                finalizar_partida(pendente["row_index"], gols_a, gols_b, pendente["time_a"], pendente["time_b"])
                st.success("Tudo salvo! O ELO foi recalculado na Planilha do Google.")
                import time
                time.sleep(2)
                st.rerun()
                
        st.stop() # PARA A EXECUÇÃO AQUI

    # --- INICIALIZAÇÃO DINÂMICA DA BASE DE ATLETAS DA PLANILHA ---
    jogadores_base, goleiros_base = obter_base_de_jogadores()

    # Sessão de Persistência (Nativa)
    if 'visitantes_list' not in st.session_state:
        st.session_state.visitantes_list = []
    if 'visitantes_ratings' not in st.session_state:
        st.session_state.visitantes_ratings = {}
    if 'visitantes_goleiros' not in st.session_state:
        st.session_state.visitantes_goleiros = []
    if 'keys_presentes' not in st.session_state:
        st.session_state.keys_presentes = []
    if 'keys_goleiros' not in st.session_state:
        st.session_state.keys_goleiros = []
    if 'sorteio_count' not in st.session_state:
        st.session_state.sorteio_count = 0
    if 'temp_visitante' not in st.session_state:
        st.session_state.temp_visitante = ""
    if 'temp_is_gol' not in st.session_state:
        st.session_state.temp_is_gol = False
    if 'temp_nivel' not in st.session_state:
        st.session_state.temp_nivel = 3

    st.markdown("### 1️⃣ Lista de Presença")
    st.info("Insira o visitante primeiro, se houver.")

    def add_visitor_callback():
        novo = st.session_state.temp_visitante.strip()
        mapa_forca = {1: 850, 2: 925, 3: 1000, 4: 1075, 5: 1150}
        forca_calculada = mapa_forca.get(st.session_state.temp_nivel, 1000)
        
        if novo and novo not in st.session_state.visitantes_list:
            st.session_state.visitantes_list.append(novo)
            st.session_state.visitantes_ratings[novo] = forca_calculada
            
            if novo not in st.session_state.keys_presentes:
                st.session_state.keys_presentes.append(novo)
            if st.session_state.temp_is_gol:
                st.session_state.visitantes_goleiros.append(novo)
                if novo not in st.session_state.keys_goleiros:
                    st.session_state.keys_goleiros.append(novo)
        
        st.session_state.temp_visitante = ""
        st.session_state.temp_is_gol = False
        st.session_state.temp_nivel = 3

    st.write("Adicione o Visitante e sua Força (1=Básico, 3=Médio, 5=Craque):")
    col_v1, col_v2, col_v3, col_v4 = st.columns([4, 2, 2, 3])
    with col_v1:
        st.text_input("Nome do Visitante", key="temp_visitante", placeholder="Ex: Jonas", label_visibility="collapsed")
    with col_v2:
        st.selectbox("Nível", [1, 2, 3, 4, 5], key="temp_nivel", label_visibility="collapsed")
    with col_v3:
        st.checkbox("🧤 Goleiro?", key="temp_is_gol")
    with col_v4:
        st.button("➕ Inserir", use_container_width=True, on_click=add_visitor_callback)

    opcoes_totais = list(dict.fromkeys(jogadores_base + goleiros_base + st.session_state.visitantes_list))

    for p in st.session_state.keys_presentes:
        if (p in goleiros_base) or (p in st.session_state.visitantes_goleiros):
            if p not in st.session_state.keys_goleiros:
                st.session_state.keys_goleiros.append(p)
    st.session_state.keys_goleiros = [g for g in st.session_state.keys_goleiros if g in st.session_state.keys_presentes]

    # HOTFIX 2: Selecionar Todos em PT-BR
    if st.checkbox("☑️ Selecionar Todos os Jogadores"):
        st.session_state.keys_presentes = opcoes_totais

    presentes = st.multiselect("Quem vai pro jogo hoje?", opcoes_totais, key="keys_presentes", placeholder="Escolha os jogadores...")

    st.markdown("### 2️⃣ Definição de Goleiros")
    st.write("Quem da lista acima vai assumir o Gol?")

    goleiros_selecionados = st.multiselect("Selecione os Goleiros:", st.session_state.keys_presentes, key="keys_goleiros")

    presentes_linha = [p for p in presentes if p not in goleiros_selecionados]
    presentes_goleiros = goleiros_selecionados

    todas_as_pessoas_count = len(presentes)

    st.markdown("---")
    if todas_as_pessoas_count > 0 and todas_as_pessoas_count % 2 != 0:
        st.warning("⚠️ **Atenção:** Número ÍMPAR. A IA fará o time mais fraco jogar com 1 a mais para equilibrar.")

    if st.button("⚖️ GERAR OS MELHORES TIMES", use_container_width=True):
        if todas_as_pessoas_count < 10:
            st.error(f"🚨 Você selecionou apenas {todas_as_pessoas_count} presentes. O mínimo para dar jogo é 10! Insira visitantes.")
        else:
            st.session_state.sorteio_count += 1
            st.session_state.hora_agora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%d/%m/%Y às %H:%M:%S")
            
            with st.spinner('A IA está separando os goleiros e equilibrando a linha na Planilha...'):
                ratings_cloud = obter_ratings_atuais()
                
                for v_nome, v_rating in st.session_state.get("visitantes_ratings", {}).items():
                    if v_nome not in ratings_cloud:  
                        ratings_cloud[v_nome] = v_rating
                
                mock_linha = [{"nome": p, "rating": ratings_cloud.get(p, 1000), "goleiro": False} for p in presentes_linha]
                mock_goleiros = [{"nome": g, "rating": ratings_cloud.get(g, 1000), "goleiro": True} for g in presentes_goleiros]
                
                time_a, time_b, gap = MatchEngine.balance_teams(mock_linha, mock_goleiros)
                
                # CHAMA REGISTRO NA NUVEM!
                registrar_auditoria_cloud(st.session_state.sorteio_count, gap, time_a, time_b)
                
                st.session_state.res_time_a = time_a
                st.session_state.res_time_b = time_b
                st.session_state.res_gap = gap

    if "res_time_a" in st.session_state:
        st.success("Equilíbrio Matemático Encontrado! 🎯")
        ta, tb = st.columns(2)
        with ta:
            st.markdown("<h3 style='color: #00d4ff; text-align: center; border-bottom: 2px solid #00d4ff;'>🔵 TIME AZUL</h3>", unsafe_allow_html=True)
            for j in st.session_state.res_time_a:
                icon = "🧤" if j.get("goleiro") else "🏃"
                st.write(f"&nbsp;&nbsp;**{icon} {j['nome']}** \n`⭐ ELO: {j['rating']}`")
            st.caption(f"🛡️ Força Time: {sum(x['rating'] for x in st.session_state.res_time_a)}")
                
        with tb:
            st.markdown("<h3 style='color: #8a2be2; text-align: center; border-bottom: 2px solid #8a2be2;'>🟣 TIME ROXO</h3>", unsafe_allow_html=True)
            for j in st.session_state.res_time_b:
                icon = "🧤" if j.get("goleiro") else "🏃"
                st.write(f"&nbsp;&nbsp;**{icon} {j['nome']}** \n`⭐ ELO: {j['rating']}`")
            st.caption(f"🛡️ Força Time: {sum(x['rating'] for x in st.session_state.res_time_b)}")
        
        st.markdown("---")
        st.info(f"⚖️ Diferença Matemática: {st.session_state.res_gap} pontos.")
        
        # HOTFIX 3 e 4: FUNÇÃO COPIAR WHATSAPP (Com V.A.R. embutido)
        msg_wpp = f"⚽ *SORTEIO PATOTA AJAX* ⚽\n"
        msg_wpp += f"📅 {datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime('%d/%m/%Y')}\n\n"
        
        msg_wpp += "🔵 *TIME AZUL*\n"
        for j in st.session_state.res_time_a:
            icon = "🧤" if j.get("goleiro") else "🏃"
            msg_wpp += f"{icon} {j['nome']}\n"
        
        msg_wpp += "\n🟣 *TIME ROXO*\n"
        for j in st.session_state.res_time_b:
            icon = "🧤" if j.get("goleiro") else "🏃"
            msg_wpp += f"{icon} {j['nome']}\n"
            
        msg_wpp += f"\n⚖️ *Equilíbrio:* {st.session_state.res_gap} pts"
        
        # Leitura da Auditoria recente para injetar no WhatsApp
        registros_var = ler_auditoria_cloud()
        if len(registros_var) >= 2:
            msg_wpp += f"\n\n🚨 *V.A.R. Cloud:* Sorteio nº {st.session_state.sorteio_count}.\n"
            msg_wpp += f"Penúltimo: {registros_var[-2]['Data_Hora']}\n"
            msg_wpp += f"Último: {registros_var[-1]['Data_Hora']}"
        elif len(registros_var) == 1:
            msg_wpp += f"\n\n🕒 *Auditoria:* Sorteio Oficial nº {st.session_state.sorteio_count} ({st.session_state.hora_agora})"
        
        st.info("👇 Clique no ícone de 'Copiar' no canto superior direito da caixa abaixo para enviar no WhatsApp:")
        # Renderiza como bloco de código. Isso cria automaticamente o botão nativo de copiar do Streamlit.
        st.code(msg_wpp, language="markdown")
        
        # Alertas visuais do VAR na interface (Mantidos)
        if len(registros_var) >= 2:
            st.error(f"🚨 **V.A.R. Cloud** ativado: Este é o sorteio **nº {st.session_state.sorteio_count}**.\n\n"
                     f"- O **penúltimo** sorteio ocorreu às: `{registros_var[-2]['Data_Hora']}`\n"
                     f"- Este **último** sorteio ocorreu às: `{registros_var[-1]['Data_Hora']}`")
        elif len(registros_var) == 1:
            st.warning(f"🕒 **Auditoria:** Sorteio Oficial nº {st.session_state.sorteio_count} ({st.session_state.hora_agora})")
        
        if st.session_state.sorteio_count > 1:
            st.error("🚨 ALERTA DA IA: Múltiplas tentativas de escolha de time detectadas.")
        
        def save_and_clear_match():
            salvar_partida_pendente(st.session_state.res_time_a, st.session_state.res_time_b)
            if 'res_time_a' in st.session_state: del st.session_state.res_time_a
            if 'res_time_b' in st.session_state: del st.session_state.res_time_b
            st.session_state.keys_presentes = []
            st.session_state.keys_goleiros = []
            st.session_state.sorteio_count = 0
            
        if st.button("💾 ENVIAR PARA A NUVEM E INICIAR PARTIDA OFICIAL", use_container_width=True, on_click=save_and_clear_match):
            st.success("Tudo salvo! Aguardando o preenchimento do placar final.")
