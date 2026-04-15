import streamlit as st
import pandas as pd
from itertools import combinations
import random
import json
import gspread
import uuid
import datetime
import streamlit.components.v1 as components

# --- CONFIGURAÇÃO E POKA YOKE: GOOGLE SHEETS CLOUD ---
@st.cache_resource
def get_gspread_client():
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
    except:
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
    k_factor = 32 if diff < 3 else (48 if diff < 5 else 64)
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
    jog_linha, gols = [], []
    try:
        sh = get_gspread_client()
        ws_base = sh.worksheet("Base_Jogadores")
        records = ws_base.get_all_records()
        for r in records:
            nome, cat, status = str(r.get("Nome", "")).strip(), str(r.get("Categoria", "")).strip(), str(r.get("Status", "")).strip()
            if not nome or cat.lower() == "fornecedor" or status.lower() == "inativo": continue
            nome_display = nome + " (DM)" if status.lower() == "dm" else nome
            if cat.lower() == "goleiro": gols.append(nome_display)
            else: jog_linha.append(nome_display)
    except:
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
        best_diff, best_combination = float('inf'), None
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

# --- INTERFACE ---
st.title("🧠 Sorteador Ajax")

# CSS: Força o contraste dos inputs resolvendo o bug de Webkit (iOS/Dark Mode)
st.markdown("""
    <style>
    div[data-baseweb="input"] { background-color: #ffffff !important; border: 1px solid #cccccc !important; border-radius: 4px !important; }
    div[data-baseweb="input"] input { color: #000000 !important; caret-color: #000000 !important; -webkit-text-fill-color: #000000 !important; }
    div[data-baseweb="input"] input::placeholder { color: #7f8c8d !important; -webkit-text-fill-color: #7f8c8d !important; }
    /* Proteção extra para o Number Input */
    div[data-testid="stNumberInput"] input { color: #000000 !important; -webkit-text-fill-color: #000000 !important; }
    </style>
""", unsafe_allow_html=True)

tab_principal, tab_audit = st.tabs(["⚙️ Sorteador Oficial", "🕵️‍♂️ V.A.R. Administrativo"])

with tab_audit:
    st.markdown("### 📋 Auditoria de Sorteios")
    if st.button("🔄 Atualizar Log"): st.rerun()
    records_audit = ler_auditoria_cloud()
    if records_audit:
        df_audit = pd.DataFrame(records_audit).tail(30)
        st.dataframe(df_audit.style.map(lambda v: 'color: #ff4444; font-weight: bold' if v == 'Suspeito' else 'color: #00ff00;', subset=['Status']), use_container_width=True)

with tab_principal:
    pendente = obter_partida_pendente()
    if pendente:
        st.error("🚨 Existe uma partida aguardando o Placar Oficial!")
        colA, colB = st.columns(2)
        with colA:
            st.markdown("<h3 style='color: #00d4ff;'>🔵 T. AZUL</h3>", unsafe_allow_html=True)
            for j in pendente['time_a']: st.markdown(f"<span style='color:#ccc; font-size:14px;'>{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}</span>", unsafe_allow_html=True)
            gols_a = st.number_input("Gols Azul", min_value=0, max_value=50, value=0, key="gols_a")
        with colB:
            st.markdown("<h3 style='color: #8a2be2;'>🟣 T. ROXO</h3>", unsafe_allow_html=True)
            for j in pendente['time_b']: st.markdown(f"<span style='color:#ccc; font-size:14px;'>{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}</span>", unsafe_allow_html=True)
            gols_b = st.number_input("Gols Roxo", min_value=0, max_value=50, value=0, key="gols_b")
        if st.button("🏆 Finalizar Partida", use_container_width=True):
            finalizar_partida(pendente["row_index"], gols_a, gols_b, pendente["time_a"], pendente["time_b"])
            st.success("ELO Recalculado!")
            st.rerun()
        st.stop()

    jogadores_base, goleiros_base = obter_base_de_jogadores()
    for key in ['visitantes_list', 'visitantes_ratings', 'visitantes_goleiros', 'keys_presentes', 'sorteio_count']:
        if key not in st.session_state: st.session_state[key] = [] if 'list' in key or 'keys' in key else ({} if 'ratings' in key else 0)

    st.markdown("### 1️⃣ Presença")
    col_v1, col_v2, col_v3, col_v4 = st.columns([4, 2, 2, 3])
    with col_v1: nome_vis = st.text_input("Visitante", key="temp_v_nome", placeholder="Ex: Jonas", label_visibility="collapsed")
    with col_v2: nivel_vis = st.selectbox("Nível", [1, 2, 3, 4, 5], index=2, key="temp_v_nivel", label_visibility="collapsed")
    with col_v3: is_gol = st.checkbox("🧤?", key="temp_v_gol")
    with col_v4:
        if st.button("➕", use_container_width=True):
            if nome_vis and nome_vis not in st.session_state.visitantes_list:
                st.session_state.visitantes_list.append(nome_vis)
                st.session_state.visitantes_ratings[nome_vis] = {1:850, 2:925, 3:1000, 4:1075, 5:1150}[nivel_vis]
                if nome_vis not in st.session_state.keys_presentes: st.session_state.keys_presentes.append(nome_vis)
                if is_gol: st.session_state.visitantes_goleiros.append(nome_vis)
                st.rerun()

    opcoes_totais = list(dict.fromkeys(jogadores_base + goleiros_base + st.session_state.visitantes_list))
    
    if st.button("☑️ Selecionar Todos os Jogadores", use_container_width=True):
        st.session_state.keys_presentes = opcoes_totais

    presentes = st.multiselect("Quem vai pro jogo?", opcoes_totais, key="keys_presentes")
    
    st.markdown("### 2️⃣ Goleiros")
    # Filtro automático dos goleiros cadastrados ou visitantes que estão presentes
    goleiros_default = [p for p in presentes if p in goleiros_base or p in st.session_state.visitantes_goleiros]
    # Retirada a 'key' para evitar conflito de estado de sessão e garantir o funcionamento do 'default'
    goleiros_sel = st.multiselect("Selecione os Goleiros:", presentes, default=goleiros_default)

    if st.button("⚖️ GERAR TIMES", use_container_width=True):
        if len(presentes) < 10: st.error("Mínimo 10 jogadores!")
        else:
            st.session_state.sorteio_count += 1
            ratings = obter_ratings_atuais()
            for v, r in st.session_state.visitantes_ratings.items():
                if v not in ratings: ratings[v] = r
            mock_l = [{"nome": p, "rating": ratings.get(p, 1000), "goleiro": False} for p in presentes if p not in goleiros_sel]
            mock_g = [{"nome": g, "rating": ratings.get(g, 1000), "goleiro": True} for g in goleiros_sel]
            ta, tb, gap = MatchEngine.balance_teams(mock_l, mock_g)
            registrar_auditoria_cloud(st.session_state.sorteio_count, gap, ta, tb)
            st.session_state.res_time_a, st.session_state.res_time_b, st.session_state.res_gap = ta, tb, gap

    if "res_time_a" in st.session_state:
        st.success("Times Equilibrados! 🎯")
        c1, c2 = st.columns(2)
        for idx, (col, time, cor, label) in enumerate(zip([c1, c2], [st.session_state.res_time_a, st.session_state.res_time_b], ["#00d4ff", "#8a2be2"], ["AZUL", "ROXO"])):
            with col:
                st.markdown(f"<h3 style='color: {cor}; text-align: center; border-bottom: 2px solid {cor};'>{label}</h3>", unsafe_allow_html=True)
                for j in time: st.write(f"**{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}** \n`ELO: {j['rating']}`")
        
        msg = f"⚽ *SORTEIO PATOTA AJAX* ⚽\n📅 {datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime('%d/%m/%Y')}\n\n🔵 *TIME AZUL*\n"
        for j in st.session_state.res_time_a: msg += f"{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}\n"
        msg += f"\n🟣 *TIME ROXO*\n"
        for j in st.session_state.res_time_b: msg += f"{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}\n"
        msg += f"\n⚖️ *Equilíbrio:* {st.session_state.res_gap} pts"
        
        registros_var = ler_auditoria_cloud()
        if len(registros_var) >= 2: msg += f"\n\n🚨 *V.A.R.:* Sorteio nº {st.session_state.sorteio_count}.\nÚltimo: {registros_var[-1]['Data_Hora']}"
        
        msg += "\n\n🔗 *Preencher Resultado:* Acesse o atalho Patota Ajax Portal · Streamlit (https://patota.streamlit.app/)"
        
        msg_safe = msg.replace('`', "'").replace('\n', '\\n')
        components.html(f"""
            <button onclick="navigator.clipboard.writeText(`{msg_safe}`).then(() => {{ this.innerText = '✅ Copiado com Sucesso!'; this.style.backgroundColor = '#128C7E'; }})" 
            style="width: 100%; padding: 15px; background-color: #25D366; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer;">
                📋 COPIAR RESUMO PARA WHATSAPP
            </button>
        """, height=65)

        if st.button("💾 INICIAR PARTIDA OFICIAL", use_container_width=True):
            salvar_partida_pendente(st.session_state.res_time_a, st.session_state.res_time_b)
            
            # Limpeza segura do cache de variáveis (Evita o StreamlitAPIException)
            chaves_para_limpar = ['res_time_a', 'res_time_b', 'res_gap', 'keys_presentes']
            for chave in chaves_para_limpar:
                if chave in st.session_state:
                    del st.session_state[chave]
            
            st.session_state.sorteio_count = 0
            st.rerun()

# --- RODAPÉ DISCRETO ---
st.markdown("---")
st.caption("Layout otimizado para celular | Suporte: Rafael Guimarães")
