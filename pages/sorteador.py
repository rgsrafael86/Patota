import streamlit as st
import pandas as pd
from itertools import combinations
import random
import json
import gspread
import uuid
import datetime
import streamlit.components.v1 as components

# ==============================================================================
# MÓDULO 1: COMUNICAÇÃO COM BANCO DE DADOS (GOOGLE SHEETS)
# ==============================================================================

@st.cache_resource
def get_gspread_client():
    """
    Autentica e conecta a aplicação ao Google Sheets.
    Poka-Yoke: Usa @st.cache_resource para manter a conexão aberta na memória do servidor.
    Se reconectássemos a cada clique, o Google bloquearia o app por excesso de requisições (Rate Limit).
    """
    SHEET_ID = "1EJ-iSyYVbdafgAWawAQL2Kc-092OVfKtNvqbZg3eWfs"
    
    # Verifica se está rodando na nuvem (Streamlit Cloud - st.secrets) ou no PC local (arquivo JSON).
    if "gcp_service_account" in st.secrets:
        from google.oauth2.service_account import Credentials
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        # Formata a chave privada corretamente para evitar erros de leitura
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
    else:
        gc = gspread.service_account(filename='gcp_credenciais.json')
    
    return gc.open_by_key(SHEET_ID)

def salvar_partida_pendente(time_a, time_b):
    """
    Grava os times recém-sorteados no GSheets com status "Pendente".
    Usa JSON para compactar os dicionários dos times em uma única célula de texto.
    """
    sh = get_gspread_client()
    ws = sh.worksheet("Historico_Partidas")
    partida_id = str(uuid.uuid4())[:8] # Gera um código único de 8 caracteres
    agora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S")
    row = [partida_id, agora, json.dumps(time_a, ensure_ascii=False), json.dumps(time_b, ensure_ascii=False), "Pendente", "", ""]
    ws.append_row(row)
    return partida_id

@st.cache_data(ttl=60)
def obter_partida_pendente():
    """
    Lê o histórico e busca de trás para frente se a última partida está "Pendente".
    O ttl=60 (Time To Live) garante que o cache se renove a cada 1 minuto se não for forçado.
    """
    import time
    for tentativa in range(2): # Poka-Yoke: Tenta 2 vezes caso a API falhe na primeira leitura
        try:
            sh = get_gspread_client()
            ws = sh.worksheet("Historico_Partidas")
            records = ws.get_all_records()
            if not records: return None
            
            # reversed(): Inicia a leitura do fim da planilha para achar o pendente mais rápido
            for i, r in enumerate(reversed(records)):
                if str(r.get("Status")).strip().lower() == "pendente":
                    import ast
                    try:
                        # ast.literal_eval transforma o texto salvo na planilha de volta em uma Lista/Dicionário Python
                        t_azul_raw = str(r.get("Time_Azul", r.get("Time_A", "[]")))
                        t_roxo_raw = str(r.get("Time_Roxo", r.get("Time_B", "[]")))
                        ta = ast.literal_eval(t_azul_raw)
                        tb = ast.literal_eval(t_roxo_raw)
                    except:
                        ta, tb = [], []
                        
                    return {
                        "id": r.get("ID_Partida", r.get("ID")),
                        "time_a": ta,
                        "time_b": tb,
                        "data": r.get("Data_Hora"),
                        "row_index": len(records) - i + 1 # Descobre a linha exata do Excel para atualizar depois
                    }
            return None
        except Exception as e:
            if tentativa == 0:
                time.sleep(2) # Pausa dramática para evitar Race Condition
                st.cache_data.clear() # Limpa a memória para tentar baixar o dado fresco
            else:
                raise e # Se falhar duas vezes, acusa o erro
    return None

# ==============================================================================
# MÓDULO 2: AUDITORIA E V.A.R. (TRANSPARÊNCIA DO SORTEIO)
# ==============================================================================

def ler_auditoria_cloud():
    try:
        sh = get_gspread_client()
        ws = sh.worksheet("Audit_Sorteios")
        return ws.get_all_records()
    except:
        return []

def obter_contagem_audit_hoje():
    """
    Filtra a aba de auditoria pela data atual (fuso de Brasília -3h).
    Retorna a quantidade de sorteios já feitos hoje e a hora do último sorteio.
    """
    try:
        registros = ler_auditoria_cloud()
        if not registros: return 0, None
        
        hoje_obj = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3)))
        hoje_str = hoje_obj.strftime("%d/%m/%Y")
        
        regs_hoje = []
        for r in registros:
            dt_str = str(r.get("Data_Hora", "")).strip()
            # Validação flexível para formatos de data com ou sem zero à esquerda
            if dt_str.startswith(hoje_str) or dt_str.startswith(hoje_obj.strftime("%#d/%#m/%Y")):
                regs_hoje.append(r)
        
        if not regs_hoje: return 0, None
        
        if len(regs_hoje) > 1:
            ultimo_horario = regs_hoje[-2].get("Data_Hora", "").split(" ")[1] # Pega o horário do penúltimo
        else:
            ultimo_horario = regs_hoje[-1].get("Data_Hora", "").split(" ")[1]
            
        return len(regs_hoje), ultimo_horario
    except:
        return 0, None

def registrar_auditoria_cloud(gap, time_a, time_b):
    """Grava na aba V.A.R. quem foi sorteado. Se for o 1º do dia, é 'Autêntico', senão 'Suspeito'."""
    try:
        sh = get_gspread_client()
        ws = sh.worksheet("Audit_Sorteios")
        
        hoje_count, _ = obter_contagem_audit_hoje()
        sorteio_num = hoje_count + 1
        
        agora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S")
        az = ", ".join([p["nome"] for p in time_a])
        rx = ", ".join([p["nome"] for p in time_b])
        status = "Autêntico" if sorteio_num == 1 else "Suspeito"
        
        ws.append_row([agora, sorteio_num, status, gap, az, rx])
        return sorteio_num
    except:
        return 1

# ==============================================================================
# MÓDULO 3: MOTOR DE ELO E FECHAMENTO DE PARTIDA
# ==============================================================================

def finalizar_partida(row_index, gols_a, gols_b, time_a, time_b):
    """
    Função crítica: Atualiza a linha do placar e recalcula o ELO de todos os 10 a 14 jogadores.
    O ELO baseia-se no método de xadrez: se um time fraco ganha de um forte, a transferência
    de pontos é gigante. Se um time forte ganha de um fraco, a transferência é mínima.
    """
    sh = get_gspread_client()
    ws_hist = sh.worksheet("Historico_Partidas")
    
    # Batch Update: Grava "Finalizada", "Gols_A", "Gols_B" de uma vez na mesma linha. Mais rápido.
    ws_hist.update(range_name=f"E{row_index}:G{row_index}", values=[["Finalizada", gols_a, gols_b]])
    
    try:
        ws_rank = sh.worksheet("Ranking_IA")
        records = ws_rank.get_all_records()
        ranking_db = {str(r['Nome']): r for r in records}
    except Exception as e:
        # Poka-Yoke: Se a planilha de ranking corromper, cria um ranking em branco rodando a 1000 pts
        st.warning(f"⚠️ Nota: Não foi possível ler o Ranking IA agora. Usando base de 1000 pts. Erro: {str(e)}")
        ranking_db = {}
    
    # Fator K (Força da variação). Goleada muda o K para 64, jogo apertado K é 32.
    diff = abs(gols_a - gols_b)
    k_factor = 32 if diff < 3 else (48 if diff < 5 else 64)
    
    # Resultado numérico: 1 (Vitória), 0.5 (Empate), 0 (Derrota)
    res_a = 1 if gols_a > gols_b else (0.5 if gols_a == gols_b else 0)
    res_b = 1 - res_a
    
    # Média de força do time
    media_a = sum(float(ranking_db.get(p['nome'], {}).get('Rating', 1000)) for p in time_a) / max(len(time_a), 1)
    media_b = sum(float(ranking_db.get(p['nome'], {}).get('Rating', 1000)) for p in time_b) / max(len(time_b), 1)
    
    def calc_novo_elo(jogador, media_adv, res):
        """Aplica a fórmula matemática do ELO System para 1 único jogador"""
        nome = jogador['nome']
        stats = ranking_db.get(nome, {"Nome": nome, "Posicao": ("Goleiro" if jogador.get('goleiro') else "Linha"), "Rating": 1000, "Jogos": 0, "Vitorias": 0, "Derrotas": 0})
        elo_atual = float(stats["Rating"])
        
        # 'exp' é a Expectativa de vitória (0.01 a 0.99)
        exp = 1 / (1 + 10 ** ((media_adv - elo_atual) / 400))
        
        # Atualiza a pontuação baseada na diferença entre o Real e o Esperado
        stats["Rating"] = round(elo_atual + k_factor * (res - exp))
        stats["Jogos"] = int(stats["Jogos"]) + 1
        if res == 1: stats["Vitorias"] = int(stats["Vitorias"]) + 1
        elif res == 0: stats["Derrotas"] = int(stats["Derrotas"]) + 1
        ranking_db[nome] = stats
        
    for p in time_a: calc_novo_elo(p, media_b, res_a)
    for p in time_b: calc_novo_elo(p, media_a, res_b)
    
    # Reconstrói a tabela do Excel inteira na memória, ordenada do Maior ELO para o Menor
    headers = ["Nome", "Posicao", "Rating", "Jogos", "Vitorias", "Derrotas"]
    linhas = [headers]
    for _, s in sorted(ranking_db.items(), key=lambda x: float(x[1]['Rating']), reverse=True):
        linhas.append([s["Nome"], s["Posicao"], s["Rating"], s["Jogos"], s["Vitorias"], s["Derrotas"]])
    
    # Apaga a aba atual e injeta a aba calculada (Overwrite total)
    ws_rank.clear()
    ws_rank.update(values=linhas, range_name="A1")

@st.cache_data(ttl=60)
def obter_ratings_atuais():
    """Baixa apenas a coluna de Rating do Ranking_IA."""
    try:
        sh = get_gspread_client()
        ws_rank = sh.worksheet("Ranking_IA")
        records = ws_rank.get_all_records()
        return {str(r['Nome']): float(r['Rating']) for r in records}
    except:
        return {}

@st.cache_data(ttl=60)
def obter_base_de_jogadores():
    """Baixa o cadastro e separa goleiros de jogadores de linha."""
    jog_linha, gols = [], []
    try:
        sh = get_gspread_client()
        ws_base = sh.worksheet("Base_Jogadores")
        records = ws_base.get_all_records()
        for r in records:
            nome, cat, status = str(r.get("Nome", "")).strip(), str(r.get("Categoria", "")).strip(), str(r.get("Status", "")).strip()
            
            # Poka-Yoke de Status: Impede que a IA leia nomes com tag de Inativo ou Departamento Médico
            if not nome or cat.lower() in ["fornecedor", "dm"] or status.lower() in ["inativo", "dm"]: 
                continue
                
            nome_display = nome
            if cat.lower() == "goleiro": gols.append(nome_display)
            else: jog_linha.append(nome_display)
    except:
        pass
    return jog_linha, gols

# ==============================================================================
# MÓDULO 4: ALGORITMO ESTATÍSTICO DE SORTEIO (MATH ENGINE)
# ==============================================================================

class MatchEngine:
    @staticmethod
    def balance_teams(players_list, goalkeepers_list):
        gk_a, gk_b = [], []
        
        # 1. Aloca os goleiros de forma rígida (Goleiro 1 no A, Goleiro 2 no B)
        if len(goalkeepers_list) >= 2:
            gk_a.append(goalkeepers_list[0])
            gk_b.append(goalkeepers_list[1])
            # Se houverem 3 ou 4 goleiros, os sobressalentes jogam na linha
            for extra_gk in goalkeepers_list[2:]:
                extra_gk["goleiro"] = False
                players_list.append(extra_gk)
        elif len(goalkeepers_list) == 1:
            gk_a.append(goalkeepers_list[0]) 

        # 2. FATOR CAOS (Anti-Vício)
        # Uma reclamação comum em softwares de ELO é dar sempre o mesmo time se as mesmas pessoas forem.
        # Nós multiplicamos o ELO real por um valor entre 0.95 e 1.05 (+- 5% de sorte ou azar no dia).
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
        
        # combinations(): Cria todas as análises combinatórias possíveis (Ex: Combinação de 10 para escolher 5 = 252)
        all_combinations = list(combinations(range(len(players_calc)), max(0, needed_a)))
        
        # Randomiza a lista de combinações geradas
        random.shuffle(all_combinations)
        
        # POKA-YOKE DE MEMÓRIA (CPU/RAM LIMITER)
        # Se 18 jogadores de linha, as combinações explodem para 48.620 possibilidades.
        # Para evitar travamento (Estouro de RAM) do servidor do Streamlit, cortamos o laço em 1000 avaliações.
        if len(all_combinations) > 1000:
            all_combinations = all_combinations[:1000]

        # Laço Matemático: Mede o "Gap" (desnível) de cada uma das possibilidades
        for combo in all_combinations:
            team_a_indices = set(combo)
            team_b_indices = set(range(len(players_calc))) - team_a_indices
            
            sum_a = sum(p['rating_calc'] for i, p in enumerate(players_calc) if i in team_a_indices) + sum(g['rating_calc'] for g in gk_calc_a)
            sum_b = sum(p['rating_calc'] for i, p in enumerate(players_calc) if i in team_b_indices) + sum(g['rating_calc'] for g in gk_calc_b)
            
            diff = abs(sum_a - sum_b)
            # Fica sempre com a combinação que tiver o diff (desnível) mais próximo de Zero.
            if diff < best_diff:
                best_diff = diff
                best_combination = (team_a_indices, team_b_indices)
        
        # Entrega os índices da melhor combinação encontrada
        team_a = gk_a + [players_list[i] for i in best_combination[0]]
        team_b = gk_b + [players_list[i] for i in best_combination[1]]
        return team_a, team_b, best_diff

# ==============================================================================
# MÓDULO 5: INTERFACE GRÁFICA (UI) STREAMLIT E CONTROLE DE ESTADO (UX)
# ==============================================================================

st.title("🧠 Sorteador Ajax")

# --- ISOLAMENTO CSS ESTRITO: Força Caixa Escura e Texto Branco ---
# Este bloco de CSS injetado no HTML resolve o bug dos iPhones e Celulares com "Modo Noturno".
# Ele "blinda" apenas os st.text_input e st.number_input, sem quebrar as setinhas dos st.multiselect.
st.markdown("""
    <style>
    div[data-testid="stTextInput"] div[data-baseweb="input"],
    div[data-testid="stNumberInput"] div[data-baseweb="input"] {
        background-color: #1e1e1e !important; /* Fundo cinza escuro forçado */
        border-radius: 6px !important;
        border: 1px solid #444444 !important;
    }
    
    div[data-testid="stTextInput"] input,
    div[data-testid="stNumberInput"] input {
        color: #ffffff !important; /* Fonte branca forçada */
        -webkit-text-fill-color: #ffffff !important;
        caret-color: #ffffff !important; /* Cursor piscante em branco */
    }
    
    div[data-testid="stTextInput"] input::placeholder {
        color: #aaaaaa !important; /* Cor fantasma do Placeholder */
        -webkit-text-fill-color: #aaaaaa !important;
    }
    </style>
""", unsafe_allow_html=True)

# Layout em duas abas (Sorteio vs Log)
tab_principal, tab_audit = st.tabs(["⚙️ Sorteador Oficial", "🕵️‍♂️ V.A.R. Administrativo"])

# ----------------- ABA 2: V.A.R. (TELA ADMINISTRATIVA) -----------------
with tab_audit:
    st.markdown("### 📋 Auditoria de Sorteios")
    if st.button("🔄 Atualizar Log"): st.rerun() # Refresh manual
    records_audit = ler_auditoria_cloud()
    if records_audit:
        df_audit = pd.DataFrame(records_audit).tail(30) # Exibe só as últimas 30 pra não pesar a tela
        # Pinta a tabela baseada na string. Vermelho se for "Suspeito".
        st.dataframe(df_audit.style.map(lambda v: 'color: #ff4444; font-weight: bold' if v == 'Suspeito' else 'color: #00ff00;', subset=['Status']), use_container_width=True)

# ----------------- ABA 1: OPERAÇÃO PRINCIPAL (TELA DA BOLA) -----------------
with tab_principal:
    # 1. BLOQUEIO DE TELA (Se existir partida gravada aguardando placar, esconde o Sorteador)
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
            with st.spinner("Computando resultados..."):
                finalizar_partida(pendente["row_index"], gols_a, gols_b, pendente["time_a"], pendente["time_b"])
                
                # Força a limpeza de cache para o servidor entender que a tabela no GSheets mudou
                obter_partida_pendente.clear()
                
                st.success("ELO Recalculado! Retornando ao sorteador vazio...")
                
                # HARD RESET: Exclusão segura das memórias via "del" (Evita TypeError e StreamlitAPIException)
                chaves_para_limpar = [
                    'res_time_a', 'res_time_b', 'res_gap', 'keys_presentes', 
                    'visitantes_list', 'visitantes_goleiros', 'visitantes_ratings', 'match_saved'
                ]
                for c in chaves_para_limpar:
                    if c in st.session_state: 
                        del st.session_state[c]
                
                import time
                time.sleep(1) # Aguarda UI terminar de apagar as variáveis
                st.rerun() # Refresh global devolvendo a tela inicial em branco
        st.stop() # Aborta a renderização do restante do código (A Tela fica travada aqui)

    # 2. SE NÃO HOUVER PARTIDA, GERA A TELA DE SORTEIO
    jogadores_base, goleiros_base = obter_base_de_jogadores()
    
    # PROTEÇÃO DE TIPAGEM (Impede que lixo no cache do navegador mobile corrompa os arrays)
    if 'visitantes_goleiros' in st.session_state and not isinstance(st.session_state.visitantes_goleiros, list):
        del st.session_state['visitantes_goleiros']
    if 'visitantes_list' in st.session_state and not isinstance(st.session_state.visitantes_list, list):
        del st.session_state['visitantes_list']
    if 'keys_presentes' in st.session_state and not isinstance(st.session_state.keys_presentes, list):
        del st.session_state['keys_presentes']
        
    # INICIALIZAÇÃO ESTRUTURAL (Cria as caixas na memória se elas não existirem)
    if 'visitantes_list' not in st.session_state: st.session_state.visitantes_list = []
    if 'visitantes_goleiros' not in st.session_state: st.session_state.visitantes_goleiros = []
    if 'keys_presentes' not in st.session_state: st.session_state.keys_presentes = []
    if 'visitantes_ratings' not in st.session_state: st.session_state.visitantes_ratings = {}
    if 'sorteio_count' not in st.session_state: st.session_state.sorteio_count = 0
    if 'match_saved' not in st.session_state: st.session_state.match_saved = False

    def inserir_visitante_callback():
        """
        Gatilho do Botão "+ Inserir".
        O uso de Callback (função amarrada ao on_click) resolve bugs de sobreposição de digitação.
        """
        nome = st.session_state.get('temp_v_nome', '').strip()
        nivel = st.session_state.get('temp_v_nivel', 3)
        goleiro = st.session_state.get('temp_v_gol', False)
        
        if nome and nome not in st.session_state.visitantes_list:
            st.session_state.visitantes_list.append(nome) # Add na base geral
            # Converte as "Estrelas" (1 a 5) em pontuação ELO fictícia (850 a 1150)
            st.session_state.visitantes_ratings[nome] = {1:850, 2:925, 3:1000, 4:1075, 5:1150}[nivel]
            
            # Adiciona ele "checado" automaticamente na lista de presença para facilitar
            if nome not in st.session_state.keys_presentes: 
                st.session_state.keys_presentes.append(nome)
            if goleiro: 
                st.session_state.visitantes_goleiros.append(nome)
            
            # Limpa o texto da caixinha (Placeholder) para receber o próximo visitante
            st.session_state.temp_v_nome = ""
            st.session_state.temp_v_gol = False

    st.markdown("### 1️⃣ Presença")
    st.caption("Adicione o Visitante e defina o Nível Técnico (1=Básico, 3=Médio, 5=Craque):")
    
    col_v1, col_v2, col_v3, col_v4 = st.columns([4, 2, 2, 3])
    with col_v1: st.text_input("Visitante", key="temp_v_nome", placeholder="Ex: Jonas", label_visibility="collapsed")
    with col_v2: st.selectbox("Nível", [1, 2, 3, 4, 5], index=2, key="temp_v_nivel", label_visibility="collapsed")
    with col_v3: st.checkbox("🧤Goleiro?", key="temp_v_gol")
    with col_v4:
        st.button("➕Inserir", use_container_width=True, on_click=inserir_visitante_callback)

    # Funde o Google Sheets (Base) com os visitantes temporários do navegador
    opcoes_totais = list(dict.fromkeys(jogadores_base + goleiros_base + st.session_state.visitantes_list))
    
    if st.button("☑️ Selecionar Todos os Jogadores", use_container_width=True):
        st.session_state.keys_presentes = opcoes_totais

    # Caixa Múltipla. O "key" amarra ela diretamente com a memória do Python.
    presentes = st.multiselect("Quem vai pro jogo?", opcoes_totais, key="keys_presentes")
    
    st.markdown("### 2️⃣ Goleiros")
    # Poka-Yoke Lógico: Se João foi assinalado no sistema geral como "Goleiro", e o organizador
    # colocar João como "Presente", essa List Comprehension entende automático que ele vai no Gol.
    goleiros_default = [p for p in presentes if p in goleiros_base or p in st.session_state.visitantes_goleiros]
    goleiros_sel = st.multiselect("Selecione os Goleiros:", presentes, default=goleiros_default)

    # 3. ROTINA DE SORTEIO E RESULTADO (Seção de Ação Final)
    if st.button("⚖️ GERAR TIMES", use_container_width=True):
        if len(presentes) < 10: st.error("Mínimo 10 jogadores!")
        else:
            with st.spinner("Consultando V.A.R. Cloud..."):
                ratings = obter_ratings_atuais() # Traz o ELO da nuvem
                for v, r in st.session_state.visitantes_ratings.items():
                    if v not in ratings: ratings[v] = r # Injeta o visitante no meio do ELO
                
                # Monta a estrutura de dados (Listas de Dicionários) para o MatchEngine processar
                mock_l = [{"nome": p, "rating": ratings.get(p, 1000), "goleiro": False} for p in presentes if p not in goleiros_sel]
                mock_g = [{"nome": g, "rating": ratings.get(g, 1000), "goleiro": True} for g in goleiros_sel]
                
                ta, tb, gap = MatchEngine.balance_teams(mock_l, mock_g)
                
                # Joga pra nuvem no "Auditor" para que fique registrado quem foi sorteado e quando.
                num_global = registrar_auditoria_cloud(gap, ta, tb)
                
                # Registra na sessão os campeões para manter na tela
                st.session_state.res_time_a, st.session_state.res_time_b, st.session_state.res_gap = ta, tb, gap
                st.session_state.num_sorteio_atual = num_global
                st.rerun()

    # Se a memória já possui "res_time_a", significa que o botão GERAR TIMES foi concluído. (Inicia a tela de Cópia)
    if "res_time_a" in st.session_state:
        st.success("Times Equilibrados! 🎯")
        c1, c2 = st.columns(2)
        for idx, (col, time, cor, label) in enumerate(zip([c1, c2], [st.session_state.res_time_a, st.session_state.res_time_b], ["#00d4ff", "#8a2be2"], ["AZUL", "ROXO"])):
            with col:
                st.markdown(f"<h3 style='color: {cor}; text-align: center; border-bottom: 2px solid {cor};'>{label}</h3>", unsafe_allow_html=True)
                for j in time: st.write(f"**{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}** \n`ELO: {j['rating']:.0f}`")
        st.markdown("---")
        st.info(f"⚖️ Diferença Matemática: {st.session_state.res_gap:.1f} pontos.")
        
        # --- LÓGICA DO ALERTA VISUAL (V.A.R) ---
        total_hoje, ultimo_hora = obter_contagem_audit_hoje()
        if total_hoje > 1:
            st.error(f"🚨 **V.A.R. Cloud Ativado:** Este é o **{total_hoje}º sorteio** registrado hoje.\n\nO sorteio anterior foi realizado às `{ultimo_hora}`.")
        else:
            st.success("✅ **Sorteio Oficial:** Este é o 1º sorteio registrado na nuvem hoje.")

        # --- CONSTRUÇÃO DA STRING (TEXTO) PARA O WHATSAPP ---
        msg = f"⚽ *SORTEIO PATOTA AJAX* ⚽\n📅 {datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime('%d/%m/%Y')}\n\n🔵 *TIME AZUL*\n"
        for j in st.session_state.res_time_a: msg += f"{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}\n"
        msg += f"\n🟣 *TIME ROXO*\n"
        for j in st.session_state.res_time_b: msg += f"{'🧤' if j.get('goleiro') else '🏃'} {j['nome']}\n"
        msg += f"\n⚖️ *Desnível entre os times:* Apenas {st.session_state.res_gap:.1f} pontos de diferença na soma geral."
        
        if total_hoje > 1:
            msg += f"\n\n🚨 *V.A.R. Cloud:* Sorteio nº {total_hoje} registrado hoje."
            msg += f"\n⚠️ *ALERTA:* Houve um sorteio anterior às {ultimo_hora}."
        else:
            msg += f"\n\n✅ *V.A.R. Cloud:* Sorteio nº 1 (Oficial)"
        
        msg += "\n\n🔗 *Preencher Resultado:* Acesse o atalho Patota Ajax Portal · Streamlit (https://patota.streamlit.app/)"
        
        # Escapa os caracteres \n e ' para não quebrar a sintaxe do Javascript do HTML abaixo
        msg_safe = msg.replace('`', "'").replace('\n', '\\n')
        
        # Botão Inteligente (Acesso Nativo). Usa HTML customizado para acessar a Área de Transferência (Clipboard) do Celular.
        # Ao clicar, ele troca o texto via 'this.innerText' para dar feedback imediato de "Copiado".
        components.html(f"""
            <button onclick="navigator.clipboard.writeText(`{msg_safe}`).then(() => {{ this.innerText = '✅ Copiado com Sucesso!'; this.style.backgroundColor = '#128C7E'; }})" 
            style="width: 100%; padding: 15px; background-color: #25D366; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; box-shadow: 0px 4px 6px rgba(0,0,0,0.2);">
                📋 COPIAR PARA WHATSAPP
            </button>
        """, height=65)

        st.warning("⚠️ **IMPORTANTE:** Após copiar, não esqueça de clicar no botão abaixo para registrar a partida no sistema!")
        
        # 4. BOTÃO FINAL DE DEPLOY DA PARTIDA
        if st.button("💾 INICIAR PARTIDA OFICIAL", use_container_width=True):
            with st.spinner("Registrando partida na nuvem e sincronizando..."):
                salvar_partida_pendente(st.session_state.res_time_a, st.session_state.res_time_b)
                
                # RACE CONDITION FIX: Dá tempo (2 seg) para o Servidor da Google gravar no disco SSD físico.
                # Sem isso, o Streamlit é mais rápido e vai ler o Gsheets antes do save consolidar.
                import time
                time.sleep(2.0)
                
                # Força o aplicativo a deletar o Cache de Leitura. Obriga-o a ir na nuvem buscar o save recente.
                obter_partida_pendente.clear()
                
                # Exclusão Estrutural Global de Estado para forçar a renderização da TELA DE PLACAR
                chaves_para_limpar = [
                    'keys_presentes', 
                    'visitantes_list', 
                    'visitantes_goleiros', 
                    'visitantes_ratings',
                    'res_time_a', 
                    'res_time_b', 
                    'res_gap'
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
