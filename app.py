import base64
from datetime import datetime, timedelta
import io
import json
import os
import re
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI, APITimeoutError, APIConnectionError

# Charge le fichier .env (si présent en local)
load_dotenv()

# Configuration de la page Streamlit
st.set_page_config(
    page_title="JEV-X // Cyberpunk Trading Terminal",
    page_icon="⚡",
    layout="wide",
)

# --- STYLE CYBERPUNK / FUTURISTE (CSS INJECTÉ) ---
st.markdown(
    """
    <style>
    @keyframes glow {
        0% { border-color: #ff2a85; box-shadow: 0 0 5px rgba(255, 42, 133, 0.2); }
        50% { border-color: #00f2fe; box-shadow: 0 0 15px rgba(0, 242, 254, 0.4); }
        100% { border-color: #ff2a85; box-shadow: 0 0 5px rgba(255, 42, 133, 0.2); }
    }

    .stApp {
        background-color: #050508;
        color: #e0e0e0;
        font-family: 'Courier New', Courier, monospace;
    }
    
    div[data-testid="stMetric"], .stDataFrame, div[data-testid="stExpander"] {
        background-color: #0d0e15;
        border: 1px solid #ff2a85;
        border-radius: 6px;
        padding: 10px;
        animation: glow 5s infinite;
    }

    h1, h2, h3 {
        color: #ff2a85 !important;
        font-family: 'Courier New', Courier, monospace;
        letter-spacing: 1px;
    }

    .stButton>button {
        background: linear-gradient(90deg, #ff2a85 0%, #7928ca 100%);
        color: white;
        border: none;
        border-radius: 4px;
        font-weight: bold;
        text-transform: uppercase;
        box-shadow: 0 0 15px rgba(255, 42, 133, 0.4);
        transition: 0.3s;
    }
    .stButton>button:hover {
        opacity: 0.85;
        box-shadow: 0 0 25px rgba(255, 42, 133, 0.8);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- GESTION DE LA PERSISTANCE FICHIER (JSON) ---
DATA_FILE = "trading_data.json"


def load_persistent_data():
  if os.path.exists(DATA_FILE):
    try:
      with open(DATA_FILE, "r") as f:
        data = json.load(f)
        return (
            data.get("virtual_balance", 10000.0),
            data.get("paper_trades", []),
            data.get("consecutive_losses", 0),
            data.get("free_credits", 10),
        )
    except:
      pass
  return 10000.0, [], 0, 10


def save_persistent_data():
  data = {
      "virtual_balance": st.session_state.virtual_balance,
      "paper_trades": st.session_state.paper_trades,
      "consecutive_losses": st.session_state.consecutive_losses,
      "free_credits": st.session_state.free_credits,
  }
  with open(DATA_FILE, "w") as f:
    json.dump(data, f)


# --- SÉCURITÉ : DOUBLE MOT DE PASSE (USER vs ADMIN) ---
if "auth_status" not in st.session_state:
  st.session_state.auth_status = None  # None, "user", ou "admin"


def check_password():
  if st.session_state.auth_status in ["user", "admin"]:
    return True

  st.markdown("## 🔒 ACCÈS RESTREINT // JEV-X TERMINAL")
  st.markdown(
      "> *Entrez votre mot de passe (Utilisateur ou Administrateur).* "
  )
  pwd = st.text_input("Mot de passe", type="password")

  col_b1, col_b2 = st.columns(2)
  if col_b1.button("CONNEXION UTILISATEUR ⚡"):
    if pwd == "jevx2026":  # Mot de passe utilisateur standard
      st.session_state.auth_status = "user"
      st.rerun()
    else:
      st.error("❌ Mot de passe utilisateur incorrect.")

  if col_b2.button("CONNEXION ADMIN 🛡️"):
    if pwd == "adminjevx2026":  # Mot de passe administrateur secret
      st.session_state.auth_status = "admin"
      st.rerun()
    else:
      st.error("❌ Mot de passe administrateur incorrect.")

  return False


if not check_password():
  st.stop()

# --- INITIALISATION DES VARIABLES DE SESSION ---
saved_balance, saved_trades, saved_losses, saved_credits = (
    load_persistent_data()
)

if "virtual_balance" not in st.session_state:
  st.session_state.virtual_balance = saved_balance
if "paper_trades" not in st.session_state:
  st.session_state.paper_trades = saved_trades
if "consecutive_losses" not in st.session_state:
  st.session_state.consecutive_losses = saved_losses
if "free_credits" not in st.session_state:
  st.session_state.free_credits = saved_credits

if "analysis_history" not in st.session_state:
  st.session_state.analysis_history = []
if "cooldown_until" not in st.session_state:
  st.session_state.cooldown_until = None
if "has_analyzed" not in st.session_state:
  st.session_state.has_analyzed = False
if "last_df" not in st.session_state:
  st.session_state.last_df = None
if "last_score" not in st.session_state:
  st.session_state.last_score = 0
if "last_ai_report" not in st.session_state:
  st.session_state.last_ai_report = ""

# --- SIDEBAR : NAVIGATION & CONFIG ---
st.sidebar.markdown("# ⚡ JEV-X // BÊTA")

if st.session_state.auth_status == "admin":
  st.sidebar.markdown(
      "🛡️ **MODE ADMIN ACTIVÉ**\n*(Crédits illimités & sans blocage)*"
  )
else:
  st.sidebar.markdown(
      f"**Crédits IA restants :** {st.session_state.free_credits}"
  )

nav_page = st.sidebar.radio(
    "Navigation",
    [
        "⚡ Aperçu & Système (Chief)",
        "🔬 Laboratoire d'Analyse (Lab)",
        "📊 Journal & Paper Trading",
        "🛡️ Centre de Risque (Risk)",
    ],
)

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Config. Marché")
ticker = st.sidebar.text_input("Ticker Actif", value="BTC-USD")
period = st.sidebar.selectbox(
    "Historique", ["1mo", "3mo", "6mo", "1y"], index=2
)
interval_choice = st.sidebar.selectbox(
    "Bougies", ["15m", "1h", "2h", "3h", "1d"], index=2
)

api_key_input = os.environ.get("OPENAI_API_KEY", "")
try:
  if "OPENAI_API_KEY" in st.secrets:
    api_key_input = st.secrets["OPENAI_API_KEY"]
except:
  pass


# --- FONCTIONS DE MARCHÉ ET CALCULS ---
@st.cache_data(ttl=1800)
def fetch_data(ticker_sym, p, interval):
  try:
    import yfinance as yf

    t_obj = yf.Ticker(ticker_sym)
    df = t_obj.history(period=p, interval=interval)
    if df.empty or len(df) < 30:
      return None
    return df
  except:
    return None


def get_market_data(ticker_sym, p, interval_c):
  if interval_c in ["2h", "3h"]:
    raw_df = fetch_data(ticker_sym, p="3mo", interval="1h")
    if raw_df is None:
      return None
    rule = "2h" if interval_c == "2h" else "3h"
    df_resampled = raw_df.resample(rule).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    })
    return df_resampled.dropna()
  else:
    return fetch_data(ticker_sym, p, interval_c)


def calculate_all_indicators(df):
  df["EMA_9"] = df["Close"].ewm(span=9, adjust=False).mean()
  df["EMA_21"] = df["Close"].ewm(span=21, adjust=False).mean()
  df["EMA_50"] = df["Close"].ewm(span=50, adjust=False).mean()
  df["EMA_200"] = df["Close"].ewm(span=200, adjust=False).mean()

  delta = df["Close"].diff()
  gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
  loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
  rs = gain / loss
  df["RSI"] = 100 - (100 / (1 + rs))

  high_low = df["High"] - df["Low"]
  high_close = np.abs(df["High"] - df["Close"].shift())
  low_close = np.abs(df["Low"] - df["Close"].shift())
  tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
  df["ATR"] = tr.rolling(window=14).mean()
  return df.dropna()


def detect_technical_signals(df):
  last = df.iloc[-1]
  prev = df.iloc[-2]
  signals = []
  score = 0

  if last["Close"] > last["EMA_50"] and last["EMA_50"] > last["EMA_200"]:
    signals.append("🟢 Tendance haussière")
    score += 2
  elif last["Close"] < last["EMA_50"] and last["EMA_50"] < last["EMA_200"]:
    signals.append("🔴 Tendance baissière")
    score -= 2

  if prev["EMA_9"] <= prev["EMA_21"] and last["EMA_9"] > last["EMA_21"]:
    signals.append("🚀 Croisement EMA haussier")
    score += 2
  elif prev["EMA_9"] >= prev["EMA_21"] and last["EMA_9"] < last["EMA_21"]:
    signals.append("⚠️ Croisement EMA baissier")
    score -= 2

  rsi = last["RSI"]
  if rsi < 30:
    signals.append(f"🟢 RSI Survente ({rsi:.1f})")
    score += 1
  elif rsi > 70:
    signals.append(f"🔴 RSI Surachat ({rsi:.1f})")
    score -= 1
  else:
    signals.append(f"⚪ RSI Neutre ({rsi:.1f})")

  return signals, score


def ask_ai_expert(df, ticker_name, signals, score):
  if not api_key_input:
    return "Erreur : Clé API OpenAI manquante dans les secrets du Cloud."

  client = OpenAI(api_key=api_key_input)
  latest = df.iloc[-1]
  prompt = f"""
    Tu es un Head Quant Trader cyberpunk. Analyse l'actif {ticker_name}. 
    Prix : {latest['Close']:.2f} | ATR : {latest['ATR']:.2f} | RSI : {latest['RSI']:.2f} | Score : {score}/5
    Signaux : {chr(10).join(signals)}
    
    Donne un plan de trade structuré sous ce format exact :
    - DIRECTION: [ACHAT ou VENTE]
    - ENTREE: [Prix conseillé sous forme de nombre pur, ex: 80872.00]
    - STOP_LOSS: [Prix du SL sous forme de nombre pur]
    - TAKE_PROFIT: [Prix du TP sous forme de nombre pur]
    - ANALYSE: [Explication détaillée et technique]
    """
  try:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es une IA de trading quantitatif de pointe, style"
                    " cyberpunk."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=400,
        temperature=0.2,
        timeout=8.0,
    )
    return response.choices[0].message.content
  except:
    return "❌ Erreur lors de l'appel à l'IA."


def parse_ai_trade_plan(report_text, current_price):
  direction = "ACHAT"
  entry = current_price
  sl = current_price * 0.95
  tp = current_price * 1.05

  try:
    dir_match = re.search(
        r"-\s*DIRECTION\s*:\s*(ACHAT|VENTE)", report_text, re.IGNORECASE
    )
    if dir_match:
      direction = dir_match.group(1).upper()

    entry_match = re.search(
        r"-\s*ENTREE\s*:\s*([0-9\.]+)", report_text, re.IGNORECASE
    )
    if entry_match:
      entry = float(entry_match.group(1))

    sl_match = re.search(
        r"-\s*STOP_LOSS\s*:\s*([0-9\.]+)", report_text, re.IGNORECASE
    )
    if sl_match:
      sl = float(sl_match.group(1))

    tp_match = re.search(
        r"-\s*TAKE_PROFIT\s*:\s*([0-9\.]+)", report_text, re.IGNORECASE
    )
    if tp_match:
      tp = float(tp_match.group(1))
  except:
    pass

  return direction, entry, sl, tp


# ==========================================
# GESTION DES PAGES
# ==========================================

if nav_page == "⚡ Aperçu & Système (Chief)":
  st.markdown("## ⚡ CHIEF // Centre de Contrôle du Terminal")
  st.markdown(
      "> *Bienvenue dans JEV-X Beta. Le système est en ligne 24/7 dans le"
      .replace("'", " ")
      + " Cloud.*"
  )

  c1, c2, c3 = st.columns(3)
  c1.metric("Capital Démo Actuel", f"{st.session_state.virtual_balance:.2f} €")
  if st.session_state.auth_status == "admin":
    c2.metric("Crédits IA Restants", "ILLIMITÉS (Admin) 🛡️")
  else:
    c2.metric("Crédits IA Restants", f"{st.session_state.free_credits} / 10")
  c3.metric("Actif Surveillé", ticker)

  st.markdown("---")
  st.markdown("### 📊 État rapide du portefeuille")
  active_count = len(
      [
          t
          for t in st.session_state.paper_trades
          if t["status"] == "⏳ En cours"
      ]
  )
  st.metric("Positions ouvertes actuellement", active_count)

elif nav_page == "🔬 Laboratoire d'Analyse (Lab)":
  st.markdown("## 🔬 LAB // Laboratoire d'Analyse Quant & IA")
  st.markdown(
      "> *Analyse technique rapide et exécution d'ordres sur l'actif* **"
      f"{ticker}**."
  )

  # Si l'utilisateur est admin, pas de blocage de crédits
  can_analyze = (
      st.session_state.auth_status == "admin"
      or st.session_state.free_credits > 0
  )

  if can_analyze:
    if st.button("LANCER L'ANALYSE QUANTITATIVE 🚀", use_container_width=True):
      raw_df = get_market_data(ticker, period, interval_choice)
      if raw_df is None or len(raw_df) < 30:
        st.error("Erreur : Données insuffisantes ou ticker invalide.")
      else:
        df = calculate_all_indicators(raw_df)
        signals, score = detect_technical_signals(df)
        ai_report = ask_ai_expert(df, ticker, signals, score)

        # On décompte un crédit uniquement si ce n'est PAS un admin
        if st.session_state.auth_status != "admin":
          st.session_state.free_credits -= 1

        st.session_state.has_analyzed = True
        st.session_state.last_df = df
        st.session_state.last_score = score
        st.session_state.last_ai_report = ai_report
        save_persistent_data()
        st.success("Analyse terminée avec succès !")
        st.rerun()
  else:
    st.warning(
        "⚡ **Quota d'analyses gratuites épuisé !** (0/10 restants). Passez à"
        " l'abonnement Pro pour débloquer l'accès illimité."
    )
    st.markdown("---")

  if st.session_state.has_analyzed and st.session_state.last_df is not None:
    df = st.session_state.last_df
    score = st.session_state.last_score
    current_price = float(df["Close"].iloc[-1])

    st.markdown("---")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Prix Actuel", f"{current_price:.2f}")
    m2.metric("RSI (14)", f"{df['RSI'].iloc[-1]:.1f}")
    m3.metric("ATR Volatilité", f"{df['ATR'].iloc[-1]:.2f}")
    m4.metric("Score Quant", f"{score}/5")

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="Prix",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["EMA_21"],
            line=dict(color="#ff2a85", width=1.5),
            name="EMA 21",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["EMA_50"],
            line=dict(color="#00f2fe", width=1.5),
            name="EMA 50",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        height=450,
        paper_bgcolor="#050508",
        plot_bgcolor="#0d0e15",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### 🤖 Rapport de l'Agent IA")
    st.markdown(st.session_state.last_ai_report)

    rec_dir, rec_entry, rec_sl, rec_tp = parse_ai_trade_plan(
        st.session_state.last_ai_report, current_price
    )
    dir_index = 0 if rec_dir == "ACHAT" else 1

    st.markdown("---")
    st.markdown("### ⚡ Exécution Automatique de Position")

    with st.expander("🚀 Ouvrir un Trade Démo (Pré-rempli par l'IA)"):
      lc1, lc2, lc3, lc4 = st.columns(4)
      l_dir = lc1.selectbox(
          "Direction", ["ACHAT", "VENTE"], index=dir_index, key="lab_dir"
      )
      l_entry = lc2.number_input(
          "Entrée", value=float(rec_entry), key="lab_entry"
      )
      l_sl = lc3.number_input(
          "Stop-Loss", value=float(rec_sl), key="lab_sl"
      )
      l_tp = lc4.number_input(
          "Take-Profit", value=float(rec_tp), key="lab_tp"
      )

      if st.button("Valider et Exécuter l'Ordre ⚡", key="lab_exec_btn"):
        st.session_state.paper_trades.append({
            "Date": datetime.now().strftime("%d/%m %H:%M"),
            "Ticker": ticker,
            "direction": l_dir,
            "entry": l_entry,
            "sl": l_sl,
            "tp": l_tp,
            "status": "⏳ En cours",
            "pnl_latent": "0.00 €",
            "pnl_win": 200.0,
            "pnl_loss": 100.0,
        })
        save_persistent_data()
        st.success("Ordre exécuté et enregistré avec succès !")
        st.rerun()

elif nav_page == "📊 Journal & Paper Trading":
  st.markdown("## 📊 REGISTRE // Journal de Paper Trading")
  st.metric("Capital Actuel", f"{st.session_state.virtual_balance:.2f} €")

  # --- BOUTON DE RAFRAÎCHISSEMENT EN TEMPS RÉEL DU PNL LATENT ---
  if st.button(
      "🔄 Actualiser les prix et PnL latent en direct",
      use_container_width=True,
  ):
    for trade in st.session_state.paper_trades:
      if trade["status"] == "⏳ En cours":
        # Récupère le prix actuel du marché pour le ticker du trade
        live_df = fetch_data(trade["Ticker"], p="1d", interval="15m")
        if live_df is not None and not live_df.empty:
          current_mkt_price = float(live_df["Close"].iloc[-1])
          entry_p = float(trade["entry"])

          # Calcul de l'écart de prix en pourcentage
          if trade["direction"] == "ACHAT":
            diff_pct = (current_mkt_price - entry_p) / entry_p
          else:
            diff_pct = (entry_p - current_mkt_price) / entry_p

          # Estimation du PnL latent (basé sur un risque de base de 100€)
          estimated_pnl = diff_pct * 2000.0
          trade["pnl_latent"] = f"{estimated_pnl:+.2f} €"
    save_persistent_data()
    st.success("Prix et PnL actualisés avec succès !")
    st.rerun()

  if st.session_state.paper_trades:
    trade_df = pd.DataFrame(st.session_state.paper_trades)
    st.dataframe(trade_df, use_container_width=True)

    st.markdown("### 🛑 Clôture Manuelle des Positions")
    active_indices = [
        i
        for i, t in enumerate(st.session_state.paper_trades)
        if t["status"] == "⏳ En cours"
    ]

    if active_indices:
      selected_idx = st.selectbox(
          "Sélectionner le trade à couper",
          active_indices,
          format_func=lambda i: (
              f"[{st.session_state.paper_trades[i]['Date']}]"
              f" {st.session_state.paper_trades[i]['direction']}"
              f" {st.session_state.paper_trades[i]['Ticker']} (Entrée:"
              f" {st.session_state.paper_trades[i]['entry']})"
          ),
      )

      col_c1, col_c2 = st.columns(2)
      if col_c1.button("✅ Encaisser (Clôture manuelle en Gain)"):
        trade = st.session_state.paper_trades[selected_idx]
        gain = trade["pnl_win"]
        st.session_state.virtual_balance += gain
        trade["status"] = "✅ Fermé (Manuel / Gagné)"
        trade["pnl_latent"] = f"+{gain} €"
        st.session_state.consecutive_losses = 0
        save_persistent_data()
        st.success(f"Trade clôturé avec succès ! +{gain} €")
        st.rerun()

      if col_c2.button("❌ Couper (Clôture manuelle en Perte / SL)"):
        trade = st.session_state.paper_trades[selected_idx]
        loss = trade["pnl_loss"]
        st.session_state.virtual_balance -= loss
        trade["status"] = "✅ Fermé (Manuel / Perdu)"
        trade["pnl_latent"] = f"-{loss} €"
        st.session_state.consecutive_losses += 1
        save_persistent_data()
        st.warning(f"Trade coupé. -{loss} €")
        st.rerun()
    else:
      st.info("Aucun trade actif à clôturer manuellement.")
  else:
    st.info("Aucun ordre enregistré dans le journal.")

  with st.expander("➕ Ouvrir un Trade Démo Manuel"):
    c1, c2, c3, c4 = st.columns(4)
    p_dir = c1.selectbox("Direction", ["ACHAT", "VENTE"], key="man_dir")
    def_price = (
        float(st.session_state.last_df["Close"].iloc[-1])
        if st.session_state.last_df is not None
        else 100.0
    )
    p_entry = c2.number_input("Entrée", value=def_price, key="man_entry")
    p_sl = c3.number_input("Stop-Loss", value=def_price * 0.95, key="man_sl")
    p_tp = c4.number_input("Take-Profit", value=def_price * 1.05, key="man_tp")

    if st.button("Exécuter l'Ordre Fictif", key="man_exec"):
      st.session_state.paper_trades.append({
          "Date": datetime.now().strftime("%d/%m %H:%M"),
          "Ticker": ticker,
          "direction": p_dir,
          "entry": p_entry,
          "sl": p_sl,
          "tp": p_tp,
          "status": "⏳ En cours",
          "pnl_latent": "0.00 €",
          "pnl_win": 200.0,
          "pnl_loss": 100.0,
      })
      save_persistent_data()
      st.success("Ordre exécuté et enregistré sur le disque !")
      st.rerun()

elif nav_page == "🛡️ Centre de Risque (Risk)":
  st.markdown("## 🛡️ RISK // Protocoles de Sécurité & Anti-Tilt")
  st.markdown(
      "Modules de contrôle automatique pour la protection du capital virtuel."
  )

  col_r1, col_r2 = st.columns(2)
  col_r1.metric(
      "Pertes Consécutives", st.session_state.consecutive_losses, delta="Max 2"
  )
  if st.session_state.cooldown_until:
    col_r2.metric(
        "Statut Cooldown",
        "BLOQUÉ 🔴",
        delta=str(st.session_state.cooldown_until),
    )
  else:
    col_r2.metric("Statut Cooldown", "SYSTÈMES OPTIMAUX 🟢")

  if st.button("Réinitialiser les sécurités / Cooldown"):
    st.session_state.consecutive_losses = 0
    st.session_state.cooldown_until = None
    save_persistent_data()
    st.success("Protocoles de sécurité réinitialisés !")
    st.rerun()
