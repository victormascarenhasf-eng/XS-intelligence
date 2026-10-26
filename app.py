import io
import re
import unicodedata
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title='XS Intelligence 2.0', page_icon='📊', layout='wide')
SPREADSHEET_ID = '1M-kJTc5QvA1OYXDtBe2ChK8iyLX_P0s7gs2TV-pRdzg'
TEAM = ['Victor', 'Lucas Valentim', 'Lucas Marçal', 'Letícia']

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

st.title('XS Intelligence 2.0')
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
        content = uploaded.getvalue()
        for sep in [None, ';', ',']:
            try:
                candidate = pd.read_csv(io.BytesIO(content), sep=sep, engine='python', dtype=str, encoding='utf-8-sig')
                if 'DATA' in candidate.columns:
                    raw = candidate
                    break
            except Exception:
                pass
if raw is None or raw.empty:
    st.warning('Não há dados para analisar.')
    st.stop()
try:
    df, invalid = prepare(raw)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
if df.empty:
    st.warning('Não há vendas fechadas com datas válidas.')
    st.stop()

with st.sidebar:
    st.header('Filtros compartilhados')
    months = sorted(df['mes'].unique())
    selected_months = st.multiselect('Meses', months, default=months[-3:])
    services = sorted(df['categoria'].unique())
    selected_services = st.multiselect('Serviços', services, default=services)
    origins = sorted(df['origem'].unique())
    selected_origins = st.multiselect('Origens', origins, default=origins)
    st.caption('O filtro de profissional é independente em cada aba para não confundir vendas e indicações.')

base = df[df['mes'].isin(selected_months) & df['categoria'].isin(selected_services) & df['origem'].isin(selected_origins)].copy()
if base.empty:
    st.warning('Sem registros para os filtros selecionados.')
    st.stop()
if invalid:
    st.warning(f'Qualidade dos dados: {invalid} venda(s) fechada(s) excluída(s) por data inválida.')

visao, equipe, individual = st.tabs(['📊 Visão geral', '👥 Comparativo da equipe', '📈 Evolução individual'])

with visao:
    m = metrics(base)
    cols = st.columns(4)
    cols[0].metric('Valor vendido', brl(m['valor']))
    cols[1].metric('Vendas fechadas', f"{m['vendas']:,}".replace(',', '.'))
    cols[2].metric('Ticket médio', brl(m['ticket']))
    cols[3].metric('Reabilitações >10 sessões', f"{m['longas']}/{m['rehab']}")
    st.caption(f"Período dos registros: {base['data'].min():%d/%m/%Y} a {base['data'].max():%d/%m/%Y}. Meses em andamento são parciais.")
    left, right = st.columns(2)
    with left:
        st.subheader('Evolução mensal')
        monthly = base.groupby('mes', as_index=False).agg(valor=('valor', 'sum'), vendas=('valor', 'size'))
        st.plotly_chart(px.bar(monthly, x='mes', y='valor', labels={'mes': 'Mês', 'valor': 'Valor vendido (R$)'}), use_container_width=True)
    with right:
        st.subheader('Mix de serviços')
        mix = base.groupby('categoria', as_index=False)['valor'].sum()
        st.plotly_chart(px.pie(mix, names='categoria', values='valor', hole=.5), use_container_width=True)
    st.subheader('Origem das vendas')
    source = base.groupby('origem', as_index=False).agg(valor=('valor', 'sum'), vendas=('valor', 'size')).sort_values('valor', ascending=False)
    st.dataframe(source.rename(columns={'origem':'Origem', 'valor':'Valor vendido (R$)', 'vendas':'Vendas'}), hide_index=True, use_container_width=True)

with equipe:
    st.subheader('Comparativo entre fisioterapeutas')
    st.caption('Vendas: campo Fisioterapeuta. Indicações: campo Indicação, independentemente de quem fechou a venda.')
    available = sorted(set(base['fisio'].map(team_name)) | set(base['indicador'].map(team_name)))
    defaults = [name for name in TEAM if name in available]
    chosen = st.multiselect('Profissionais a comparar', available, default=defaults or available, key='team_select')
    rows = []
    for name in chosen:
        sold = base[base['fisio'].map(norm) == norm(name)]
        referred = base[base['indicador'].map(norm) == norm(name)]
        m = metrics(sold)
        rows.append({'Fisioterapeuta': name, 'Vendas': m['vendas'], 'Valor vendido (R$)': m['valor'],
                     'Ticket médio (R$)': m['ticket'], 'Indicações (vendas)': len(referred),
                     'Valor das indicações (R$)': float(referred['valor'].sum()),
                     'Reabilitações >10 (%)': round(m['percentual_longo'], 1) if m['percentual_longo'] is not None else None,
                     'Sessões vendidas (informadas)': float(sold['sessoes'].sum()) if sold['sessoes'].notna().any() else None})
    comp = pd.DataFrame(rows)
    if comp.empty:
        st.info('Selecione ao menos um profissional.')
    else:
        st.dataframe(comp.sort_values('Valor vendido (R$)', ascending=False), use_container_width=True, hide_index=True,
                     column_config={'Valor vendido (R$)': st.column_config.NumberColumn(format='R$ %.2f'),
                                    'Ticket médio (R$)': st.column_config.NumberColumn(format='R$ %.2f'),
                                    'Valor das indicações (R$)': st.column_config.NumberColumn(format='R$ %.2f'),
                                    'Reabilitações >10 (%)': st.column_config.NumberColumn(format='%.1f%%')})
        ranking = st.selectbox('Ranking por indicador', ['Valor vendido (R$)', 'Vendas', 'Ticket médio (R$)', 'Indicações (vendas)', 'Valor das indicações (R$)', 'Reabilitações >10 (%)', 'Sessões vendidas (informadas)'])
        ranked = comp.sort_values(ranking, ascending=False, na_position='last')
        st.plotly_chart(px.bar(ranked, x='Fisioterapeuta', y=ranking, text_auto='.2s'), use_container_width=True)
    st.info('Atendimentos realizados e taxas por 100 atendimentos ainda não estão disponíveis: exigem integração da aba Base | Atendimentos. Taxa de conversão exige oportunidades/leads atribuídos a cada profissional.')

with individual:
    st.subheader('Evolução individual')
    people = sorted(set(df['fisio'].map(team_name)) | set(df['indicador'].map(team_name)))
    initial = next((name for name in TEAM if name in people), people[0])
    selected = st.selectbox('Profissional', people, index=people.index(initial))
    mode = st.radio('Analisar', ['Vendas realizadas', 'Indicações geradas'], horizontal=True)
    # Respeita os filtros de serviço e origem, mas considera todos os meses para mostrar a série histórica.
    historical = df[df['categoria'].isin(selected_services) & df['origem'].isin(selected_origins)].copy()
    field = 'fisio' if mode == 'Vendas realizadas' else 'indicador'
    person = historical[historical[field].map(norm) == norm(selected)]
    if person.empty:
        st.info('Não há registros históricos desse profissional nos filtros de serviço e origem.')
    else:
        history = person.groupby('mes', as_index=False).agg(valor=('valor', 'sum'), vendas=('valor', 'size'))
        history['ticket'] = history['valor'] / history['vendas']
        start = '2025-07'
        post_ts = history[history['mes'] >= start]
        avg = post_ts['valor'].mean() if not post_ts.empty else None
        a, b, c = st.columns(3)
        a.metric('Total histórico', brl(float(person['valor'].sum())))
        b.metric('Vendas associadas', str(len(person)))
        c.metric('Média mensal pós-TS*', brl(float(avg)) if avg is not None else '—')
        st.plotly_chart(px.line(history, x='mes', y='valor', markers=True, labels={'mes':'Mês', 'valor':'Valor (R$)'}), use_container_width=True)
        st.dataframe(history.rename(columns={'mes':'Mês', 'valor':'Valor (R$)', 'vendas':'Vendas', 'ticket':'Ticket médio (R$)'}), hide_index=True, use_container_width=True)
        st.caption('* Média calculada sobre meses com registros para este profissional, desde julho/2025. Meses sem vendas não entram no denominador; não é uma média de meses-calendário.')

st.divider()
st.caption('Resultados profissionais compartilhados. Não são exibidos dados pessoais de pacientes. Proteja o acesso ao aplicativo: a URL pública não equivale a controle de acesso.')
