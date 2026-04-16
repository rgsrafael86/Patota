import streamlit as st
import pandas as pd
from itertools import combinations
import random
import json
import gspread
from gspread.exceptions import APIError
import uuid
import datetime
import unicodedata
import streamlit.components.v1 as components
import time

# ==============================================================================
# MÓDULO 0: UTILITÁRIOS E NORMALIZAÇÃO DE DADOS (POKA-YOKE)
# ==============================================================================

def padronizar_nome(nome):
    """Normaliza a string para atuar como Chave Primária segura no Banco de Dados."""
    if not nome: return ""
    nome = str(nome).strip().upper()
    nome = ''.join(c for c in unicodedata.normalize('NFD', nome) if unicodedata.category(c) != 'Mn')
    return nome

# ==============================================================================
# MÓDULO 1: COMUNICAÇÃO COM BANCO DE DADOS (GOOGLE SHEETS)
# ==============================================================================

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
    try:
        sh = get_gspread_client()
        ws = sh.worksheet("Historico_Partidas")
        partida_id = str(uuid.uuid4())[:8]
        agora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S")
        t_a_clean = [{"nome": padronizar_nome(p["nome"]), "goleiro": p["goleiro"], "rating": p["rating"]} for p in time_a]
        t_b_clean = [{"nome": padronizar_nome(p["nome"]), "goleiro": p["goleiro"], "rating": p["rating"]} for p in time_b]
        row = [partida_id, agora, json.dumps(t_a_clean, ensure_ascii=False), json.dumps(t_b_clean, ensure_ascii=False), "Pendente", "", ""]
        ws.append_row(row)
        return partida_id
    except APIError:
        st.error("🔌 Disjuntor de Rede (Google Quota): Limite de requisições atingido ao tentar salvar. Aguarde 60 segundos.")
        st.stop()
    except Exception as e:
        st.error(f"Falha de sistema ao gravar partida: {e}")
        st.stop()

@st.cache_data(ttl=60)
def obter_partida_pendente():
    # RELÉ TÉRMICO: Tenta 3 vezes usando Recuo Exponencial para burlar bloqueios de milissegundos
    for tentativa in range(3):
        try:
            sh = get_gspread_client()
            ws = sh.worksheet("Historico_Partidas")
            records = ws.get_all_records()
            if not records: return None
            
            for i, r in enumerate(reversed(records)):
                if str(r.get("Status")).strip().lower() == "pendente":
                    import ast
                    try:
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
                        "row_index": len(records) - i + 1 
                    }
            return None
        except APIError:
            if tentativa < 2:
                time.sleep(1.5 ** tentativa) # Tenta novamente em 1.5s, depois 2.25s
            else:
                st.error("🔌 Erro 429: Cota de leitura do Google Sheets estourou. O sistema se protegeu para não travar. Aguarde 1 minuto e recarregue a página.")
                st.stop() # Aborta a execução graciosamente
        except Exception as e:
            if tentativa < 2:
                time.sleep(2)
            else:
                st.error(f"Falha de comunicação com servidor: {e}")
                st.stop()
    return None

# ==============================================================================
# MÓDULO 2: AUDITORIA E V.A.R.
# ==============================================================================

def ler_auditoria_cloud():
    try:
        sh = get_gspread_client()
        ws = sh.worksheet("Audit_Sorteios")
        return ws.get_all_records()
    except:
        return []

def obter_contagem_audit_hoje():
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
        return sorteio_num
    except:
        return 1

# ==============================================================================
# MÓDULO 3: MOTOR DE ELO E FECHAMENTO DE PARTIDA (OTIMIZADO E BLINDADO)
# ==============================================================================

def finalizar_partida(row_index, gols_a, gols_b, time_a, time_b):
    try:
        sh = get_gspread_client()
        ws_hist = sh.worksheet("Historico_Partidas")
        # 1. Update do Histórico
        ws_hist.update(range_name=f"E{row_index}:G{row_index}", values=[["Finalizada", gols_a, gols_b]])
    except APIError:
        st.error("🔌 Falha de API no Google Sheets ao registrar o placar. O Histórico de Partidas está bloqueado temporariamente (Aguarde 60s).")
        st.stop()
    
    time.sleep(1.0) # Respiro obrigatório para não ativar firewall do Google
    
    try:
        ws_rank = sh.worksheet("Ranking_IA")
        records = ws_rank.get_all_records()
        ranking_db = {padronizar_nome(r['Nome']): r for r in records}
    except Exception as e:
        st.warning(f"⚠️ Nota: Cota de leitura do Ranking falhou. Computando na memória local. Erro: {str(e)}")
        ranking_db = {}
    
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
        exp = 1 / (1 + 10 ** ((media_adv - elo_atual) / 400))
        
        stats["Rating"] = round(elo_atual + k_factor * (res - exp))
        stats["Jogos"] = int(stats["Jogos"]) + 1
        if res == 1: stats["Vitorias"] = int(stats["Vitorias"]) + 1
        elif res == 0: stats["Derrotas"] = int(stats["Derrotas"]) + 1
        ranking_db[nome_clean] = stats
        
    for p in time_a: calc_novo_elo(p, media_b, res_a)
    for p in time_b: calc_novo_elo(p, media_a, res_b)
    
    headers = ["Nome", "Posicao", "Rating", "Jogos", "Vitorias", "Derrotas"]
    linhas = [headers]
    for _, s in sorted(ranking_db.items(), key=lambda x: float(x[1]['Rating']), reverse=True):
        linhas.append([s["Nome"], s["Posicao"], s["Rating"], s["Jogos"], s["Vitorias"], s["Derrotas"]])
    
    time.sleep(1.0) # Segundo respiro antes da gravação final
    
    try:
        ws_rank.update(values=linhas, range_name="A1")
    except APIError:
        st.error("🔌 Placar foi registrado, mas o motor falhou ao salvar a atualização do Ranking_IA na nuvem devido a excesso de requisições. Você precisará reprocessar o placar.")
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
# MÓDULO 4: MOTOR DE ELO MATEMÁTICO
# ==============================================================================

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
        elif len
