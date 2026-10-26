import io
import re
import unicodedata
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="XS Intelligence", page_icon="📊", layout="wide")
SPREADSHEET_ID = "1M-kJTc5QvA1OYXDtBe2ChK8iyLX_P0s7gs2TV-pRdzg"


def norm(v):
    s = str(v if pd.notna(v) else "").strip()
    return "".join(c for c in unicodedata.normalize("NFD", s.upper()) if unicodedata.category(c) != "Mn")


def brl(x):
    return f"R$ {x:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")


def parse_brl(x):
    if pd.isna(x):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = re.sub(r"[^0-9,.\-]", "", str(x))
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


@st.cache_data(ttl=300, show_spinner="Lendo planilha da XS...")
def get_sales(sheet_id, credentials):
    import gspread
    gc = gspread.service_account_from_dict(credentials)
    ws = gc.open_by_key(sheet_id).worksheet("VENDAS")
    rows = ws.get_all_values()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows[1:], columns=[str(h).strip() for h in rows[0]])


def prepare(raw):
    df = raw.copy()
    df.columns = [str(x).strip() for x in df.columns]
    required = {"DATA", "Status", "Valor", "Fisioterapeuta", "Serviço", "Indicação", "REF. INDICAÇÃO"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError("Colunas ausentes: " + ", ".join(sorted(missing)))
    df = df[df["Status"].map(norm) == "FECHADO"].copy()
    df["data"] = pd.to_datetime(df["DATA"].astype(str).str.strip(), format="%d/%m/%Y", errors="coerce")
    invalid = int(df["data"].isna().sum() + ((df["data"].dt.year < 2020) & df["data"].notna()).sum())
    df = df[df["data"].notna() & (df["data"].dt.year >= 2020)].copy()
    df["valor"] = df["Valor"].map(parse_brl)
    df["mes"] = df["data"].dt.strftime("%Y-%m")
    df["fisio"] = df["Fisioterapeuta"].fillna("").astype(str).str.strip().replace("", "Não informado")
    df["origem"] = df["REF. INDICAÇÃO"].fillna("").astype(str).str.strip().replace("", "Não informada")
    df["indicador"] = df["Indicação"].fillna("").astype(str).str.strip().replace("", "Não informado")
    serv = df["Serviço"].map(norm)
    df["categoria"] = serv.map(lambda s: "Reabilitação" if "REABILITA" in s else "Recovery" if "RECOVERY" in s else "Outros")
    df["sessoes"] = pd.to_numeric(df.get("Sessões", pd.Series(index=df.index, dtype=str)).astype(str).str.replace(",", "."), errors="coerce")
    return df, invalid


st.title("XS Intelligence")
st.caption("Indicadores comerciais da fisioterapia • Fonte: aba VENDAS • Atualização de dados em cache por até 5 minutos")

raw = None
if "google_service_account" in st.secrets:
    try:
        raw = get_sales(st.secrets.get("spreadsheet_id", SPREADSHEET_ID), dict(st.secrets["google_service_account"]))
    except Exception as exc:
        st.error("Não foi possível ler a planilha. Confira a permissão da conta de serviço e os Secrets.")
        st.caption(f"Detalhe técnico: {type(exc).__name__}")

if raw is None:
    st.info("Conecte a conta de serviço nos Secrets para atualização automática. Para testar agora, envie uma exportação CSV ou XLSX da aba VENDAS.")
    uploaded = st.file_uploader("Carregar VENDAS", type=["csv", "xlsx"])
    if uploaded:
        if uploaded.name.lower().endswith(".xlsx"):
            raw = pd.read_excel(uploaded, sheet_name="VENDAS", dtype=str)
        else:
            content = uploaded.getvalue()
            for sep in [None, ";", ","]:
                try:
                    candidate = pd.read_csv(io.BytesIO(content), sep=sep, engine="python", dtype=str, encoding="utf-8-sig")
                    if "DATA" in candidate.columns:
                        raw = candidate
                        break
                except Exception:
                    continue
    if raw is None:
        st.stop()

try:
    df, invalid = prepare(raw)
except ValueError as e:
    st.error(str(e))
    st.stop()

if df.empty:
    st.warning("Não há vendas fechadas com datas válidas.")
    st.stop()

with st.sidebar:
    st.header("Filtros")
    months = sorted(df["mes"].unique().tolist())
    default_months = months[-3:] if len(months) >= 3 else months
    selected_months = st.multiselect("Períodos (AAAA-MM)", months, default=default_months)
    people = sorted(df["fisio"].unique().tolist())
    selected_people = st.multiselect("Fisioterapeutas", people, default=people)
    services = sorted(df["categoria"].unique().tolist())
    selected_services = st.multiselect("Tipo de serviço", services, default=services)
    origins = sorted(df["origem"].unique().tolist())
    selected_origins = st.multiselect("Origem", origins, default=origins)
    st.caption("Filtros afetam todos os indicadores e gráficos.")

f = df[df["mes"].isin(selected_months) & df["fisio"].isin(selected_people) & df["categoria"].isin(selected_services) & df["origem"].isin(selected_origins)].copy()
if f.empty:
    st.warning("Não há vendas para os filtros selecionados.")
    st.stop()

revenue = float(f["valor"].sum())
count = len(f)
rehab = f[f["categoria"] == "Reabilitação"]
long = int((rehab["sessoes"] > 10).sum())
cols = st.columns(4)
cols[0].metric("Valor vendido", brl(revenue))
cols[1].metric("Vendas fechadas", f"{count:,}".replace(",", "."))
cols[2].metric("Ticket médio", brl(revenue / count))
cols[3].metric("Reabilitações >10 sessões", f"{long}/{len(rehab)}" if len(rehab) else "—")

if invalid:
    st.warning(f"Qualidade dos dados: {invalid} venda(s) fechada(s) com data inválida foram excluídas.")

st.caption(f"Período selecionado: {f['data'].min():%d/%m/%Y} a {f['data'].max():%d/%m/%Y}. O mês mais recente pode estar incompleto.")

monthly = f.groupby("mes", as_index=False).agg(valor=("valor", "sum"), vendas=("valor", "size"))
left, right = st.columns(2)
with left:
    st.subheader("Evolução mensal")
    st.plotly_chart(px.bar(monthly, x="mes", y="valor", labels={"mes": "Mês", "valor": "Valor vendido (R$)"}), use_container_width=True)
with right:
    st.subheader("Mix de serviços")
    mix = f.groupby("categoria", as_index=False)["valor"].sum()
    st.plotly_chart(px.pie(mix, names="categoria", values="valor", hole=.55), use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("Por fisioterapeuta")
    perf = f.groupby("fisio", as_index=False).agg(valor=("valor", "sum"), vendas=("valor", "size")).sort_values("valor", ascending=False)
    st.plotly_chart(px.bar(perf, x="fisio", y="valor", labels={"fisio": "Profissional", "valor": "Valor vendido (R$)"}), use_container_width=True)
with right:
    st.subheader("Origem das vendas")
    src = f.groupby("origem", as_index=False).agg(valor=("valor", "sum"), vendas=("valor", "size")).sort_values("valor", ascending=False)
    st.plotly_chart(px.bar(src, x="origem", y="valor", labels={"origem": "Origem", "valor": "Valor vendido (R$)"}), use_container_width=True)

st.subheader("Comparativo de profissionais")
perf["ticket_medio"] = perf["valor"] / perf["vendas"]
st.dataframe(perf.rename(columns={"fisio": "Fisioterapeuta", "valor": "Valor vendido (R$)", "vendas": "Vendas", "ticket_medio": "Ticket médio (R$)"}), use_container_width=True, hide_index=True)

st.subheader("Indicações geradas")
ind = f.groupby("indicador", as_index=False).agg(valor=("valor", "sum"), vendas=("valor", "size")).sort_values("valor", ascending=False)
st.dataframe(ind.rename(columns={"indicador": "Indicador", "valor": "Valor vendido (R$)", "vendas": "Vendas"}).head(30), use_container_width=True, hide_index=True)

st.divider()
st.caption("Vendas são atribuídas ao campo Fisioterapeuta; indicações ao campo Indicação. Dados pessoais de pacientes não são exibidos. Não publique este aplicativo como público sem aprovação da XS e revisão de segurança.")
