import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import cv2
import gspread
import numpy as np
import pandas as pd
import qrcode
import streamlit as st
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="CerezOS Harvest Manager", page_icon="🍒", layout="wide")

st.markdown(
    """
    <style>
    .main { background-color: #fcf5f7; }
    .stButton>button, .stFormSubmitButton>button {
        background-color: #722F37; color: white; border-radius: 8px;
        font-weight: bold; width: 100%;
    }
    .stButton>button:hover, .stFormSubmitButton>button:hover {
        background-color: #58222A; color: white;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

TZ = ZoneInfo("America/Santiago")
KG_POR_BALDE = 5
HEADERS = ["Fecha/Hora", "Planillero", "Trabajador", "Baldes", "Cajas"]
workers = ["Ana", "Carlos", "Luis", "María", "José"]
planilleros = ["Juan", "Pedro", "Sofía"]
planilleros = [f"PLAN-{i:03d}" for i in range(1, 6)]


# ---------- Clave de acceso opcional (evita que cualquiera con el link registre) ----------
if "PIN" in st.secrets:
    if not st.session_state.get("pin_ok"):
        pin = st.text_input("Clave de acceso", type="password")
        if pin:
            if pin == str(st.secrets["PIN"]):
                st.session_state.pin_ok = True
                st.rerun()
            else:
                st.error("Clave incorrecta")
        st.stop()


# ---------- Google Sheets ----------
@st.cache_resource
def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=scopes
    )
    ws = gspread.authorize(creds).open_by_key(st.secrets["SHEET_ID"]).sheet1
    if ws.row_values(1) != HEADERS:
        ws.insert_row(HEADERS, 1)
    return ws


@st.cache_data(ttl=8)
def read_logs():
    rows = get_sheet().get_all_records()
    return pd.DataFrame(rows, columns=HEADERS)


def save_log(planillero, trabajador, baldes, cajas):
    now = datetime.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    get_sheet().append_row(
        [now, planillero, trabajador, int(baldes), int(cajas)],
        value_input_option="USER_ENTERED",
    )
    read_logs.clear()


# ---------- QR ----------
@st.cache_data
def generate_qr(text):
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#722F37", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def decode_qr(foto):
    arr = np.frombuffer(foto.getvalue(), np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return ""
    det = cv2.QRCodeDetector()
    data, _, _ = det.detectAndDecode(img)
    if not data:  # segundo intento en escala de grises ampliada
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=1.5, fy=1.5)
        data, _, _ = det.detectAndDecode(gray)
    return data.strip().upper()


# ---------- Estado ----------
st.session_state.setdefault("trab", workers[0])
st.session_state.setdefault("plan", planilleros[0])
st.session_state.setdefault("cam_n", 0)

st.sidebar.title("🍒 CerezOS Manager")
st.sidebar.markdown("Panel de Control Agrícola")
menu = st.sidebar.radio(
    "Navegación", ["Registro de Terreno", "Credenciales QR", "Historial y Reportes"]
)

# ---------- MÓDULO 1: REGISTRO ----------
if menu == "Registro de Terreno":
    st.header("📲 Registro de Baldes y Cajas")

    with st.expander("📷 Escanear QR del trabajador", expanded=False):
        foto = st.camera_input(
            "Apunta al QR y toma la foto", key=f"cam{st.session_state.cam_n}"
        )
        if foto:
            code = decode_qr(foto)
            if code in workers:
                st.session_state.trab = code
                st.success(f"Trabajador detectado: {code}")
            elif code in planilleros:
                st.session_state.plan = code
                st.success(f"Planillero detectado: {code}")
            else:
                st.warning("No se pudo leer el QR. Acércate e intenta de nuevo, o elige de la lista.")

    c1, c2 = st.columns(2)
    c1.selectbox("Planillero (Responsable)", planilleros, key="plan")
    c2.selectbox("Trabajador (Cosechador)", workers, key="trab")

    with st.form("form_registro", clear_on_submit=True):
        cb, cc = st.columns(2)
        baldes = cb.number_input("Baldes / Capachos", 0, 50, 1)
        cajas = cc.number_input("Cajas", 0, 20, 0)
        if st.form_submit_button("💾 Guardar Registro de Producción"):
            if baldes == 0 and cajas == 0:
                st.error("Ingresa al menos 1 balde o 1 caja.")
            else:
                try:
                    save_log(st.session_state.plan, st.session_state.trab, baldes, cajas)
                    st.success(
                        f"✔ Guardado: {st.session_state.trab} – {baldes} baldes, {cajas} cajas"
                    )
                    st.session_state.cam_n += 1  # reinicia la cámara para el siguiente
                except Exception as e:
                    st.error(f"No se pudo guardar, intenta de nuevo. ({type(e).__name__})")

    st.markdown("---")
    st.subheader("📊 Resumen de la Jornada")
    try:
        df = read_logs()
        if not df.empty:
            hoy = datetime.datetime.now(TZ).strftime("%Y-%m-%d")
            dfh = df[df["Fecha/Hora"].astype(str).str.startswith(hoy)]
            tb, tc = int(dfh["Baldes"].sum()), int(dfh["Cajas"].sum())
            m1, m2, m3 = st.columns(3)
            m1.metric("Baldes hoy", tb)
            m2.metric("Cajas hoy", tc)
            m3.metric("Kilos aprox.", f"{tb * KG_POR_BALDE} kg")
            st.dataframe(dfh.iloc[::-1].head(30), use_container_width=True)
        else:
            st.info("Aún no hay registros.")
    except Exception as e:
        st.warning(f"No se pudo leer la planilla ({type(e).__name__}).")

# ---------- MÓDULO 2: QR ----------
elif menu == "Credenciales QR":
    st.header("🖨️ Credenciales QR para Imprimir")
    tipo = st.radio("Seleccione tipo:", ["Trabajadores", "Planilleros"], horizontal=True)
    lista = workers if tipo == "Trabajadores" else planilleros
    cols = st.columns(3)
    for i, item in enumerate(lista):
        with cols[i % 3]:
            st.markdown(f"### **{item}**")
            st.image(generate_qr(item), width=150)
            st.markdown("---")

# ---------- MÓDULO 3: HISTORIAL ----------
else:
    st.header("📋 Historial Completo y Exportación")
    try:
        df = read_logs()
        if df.empty:
            st.warning("No hay registros.")
        else:
            st.dataframe(df, use_container_width=True)
            resumen = df.groupby("Trabajador")[["Baldes", "Cajas"]].sum().reset_index()
            st.subheader("Total por trabajador")
            st.dataframe(resumen, use_container_width=True)
            st.download_button(
                "📥 Descargar CSV (Excel)",
                df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"cosecha_cerezos_{datetime.date.today()}.csv",
                mime="text/csv",
            )
    except Exception as e:
        st.warning(f"No se pudo leer la planilla ({type(e).__name__}).")
