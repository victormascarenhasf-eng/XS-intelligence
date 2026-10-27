import io
import re
import unicodedata
import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title='XS Intelligence 2.5', page_icon='📊', layout='wide')
SPREADSHEET_ID = '1M-kJTc5QvA1OYXDtBe2ChK8iyLX_P0s7gs2TV-pRdzg'
TEAM = ['Victor', 'Lucas Valentim', 'Lucas Marçal', 'Letícia']
GOALS = {'Lucas Marçal': 20750.0, 'Victor': 19400.0, 'Lucas Valentim': 12750.0, 'Letícia': 2100.0}
CLINIC_GOAL = 55000.0

def norm(value):
    text = str(value if pd.notna(value) else '').strip()
    return ''.join(c for c in unicodedata.normalize('NFD', text.upper()) if unicodedata.category(c) != 'Mn')

def brl(value):
    return f'R$ {value:,.2f}'.replace(',', '#').replace('.', ',').replace('#', '.')

def parse_brl(value):
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r'[^0-9,.\-]', '', str(value))
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    elif text.count('.') > 1:
        text = text.replace('.', '')
    try:
        return float(text)
    except ValueError:
        return 0.0

@st.cache_data(ttl=300, show_spinner='Atualizando vendas...')
def get_sales(sheet_id, credentials):
    import gspread
    client = gspread.service_account_from_dict(credentials)
    values = client.open_by_key(sheet_id).worksheet('VENDAS').get_all_values()
    return pd.DataFrame(values[1:], columns=[str(h).strip() for h in values[0]]) if values else pd.DataFrame()

def prepare(raw):
    df = raw.copy()
    df.columns = [str(col).strip() for col in df.columns]
    required = {'DATA', 'Status', 'Valor', 'Fisioterapeuta', 'Serviço', 'Indicação', 'REF. INDICAÇÃO'}
    if required - set(df.columns):
        raise ValueError('Colunas ausentes: ' + ', '.join(sorted(required - set(df.columns))))
    df = df[df['Status'].map(norm) == 'FECHADO'].copy()
    df['data'] = pd.to_datetime(df['DATA'].astype(str).str.strip(), format='%d/%m/%Y', errors='coerce')
    invalid = int((df['data'].isna() | (df['data'].dt.year < 2020)).sum())
    df = df[df['data'].notna() & (df['data'].dt.year >= 2020)].copy()
    df['valor'] = df['Valor'].map(parse_brl)
    df['mes'] = df['data'].dt.strftime('%Y-%m')
    df['fisio'] = df['Fisioterapeuta'].fillna('').astype(str).str.strip().replace('', 'Não informado')
    df['indicador'] = df['Indicação'].fillna('').astype(str).str.strip().replace('', 'Não informado')
    df['origem'] = df['REF. INDICAÇÃO'].fillna('').astype(str).str.strip().replace('', 'Não informada')
    df['categoria'] = df['Serviço'].map(norm).map(lambda x: 'Reabilitação' if 'REABILITA' in x else ('Recovery' if 'RECOVERY' in x else 'Outros'))
    df['sessoes'] = pd.to_numeric(df.get('Sessões', pd.Series(index=df.index, dtype=str)).astype(str).str.replace(',', '.', regex=False), errors='coerce')
    df['fisio_key'] = df['fisio'].map(norm)
    df['indicador_key'] = df['indicador'].map(norm)
    return df, invalid

def metrics(frame):
    rehab = frame[frame['categoria'] == 'Reabilitação']
    n = len(frame)
    return {'valor': float(frame['valor'].sum()), 'vendas': n, 'ticket': float(frame['valor'].sum()) / n if n else 0,
            'longas': int((rehab['sessoes'] > 10).sum()), 'rehab': len(rehab),
            'percentual_longo': 100 * (rehab['sessoes'] > 10).sum() / len(rehab) if len(rehab) else None}

def team_name(value):
    key = norm(value)
    for name in TEAM:
        if key == norm(name):
            return name
    return value

st.title('XS Intelligence 2.5')
st.caption('Gestão comercial e desempenho compartilhado • Fonte: VENDAS • Atualização automática em até 5 minutos')
raw = None
if 'google_service_account' in st.secrets:
    try:
        raw = get_sales(st.secrets.get('spreadsheet_id', SPREADSHEET_ID), dict(st.secrets['google_service_account']))
    except Exception as exc:
        st.error('Falha ao acessar a planilha. Confira as permissões e os Secrets.')
        st.caption(f'Tipo do erro: {type(exc).__name__}')
if raw is None:
    uploaded = st.file_uploader('Carregar exportação da aba VENDAS (opcional)', type=['xlsx', 'csv'])
    if uploaded is None:
        st.stop()
    if uploaded.name.lower().endswith('.xlsx'):
        raw = pd.read_excel(uploaded, sheet_name='VENDAS', dtype=str)
    else:
