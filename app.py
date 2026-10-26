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

def service_stats(frame, prefix):
    result = {}
    for category, slug in [('Reabilitação', 'Reabilitação'), ('Recovery', 'Recovery')]:
        part = frame[frame['categoria'] == category]
        result[f'{prefix} {slug} (nº)'] = len(part)
        result[f'{prefix} {slug} (R$)'] = float(part['valor'].sum())
        result[f'{prefix} Ticket {slug} (R$)'] = float(part['valor'].mean()) if len(part) else None
    return result


def month_series(frame, all_months, label):
    grouped = frame.groupby('mes').agg(faturamento=('valor', 'sum'), quantidade=('valor', 'size'))
    grouped = grouped.reindex(all_months, fill_value=0).reset_index().rename(columns={'index': 'mes'})
    grouped['Dimensão'] = label
    return grouped


with equipe:
    st.subheader('Ranking e comparativo dos fisioterapeutas')
    st.caption('Vendas fechadas = coluna Fisioterapeuta. Indicações geradas = coluna Indicação. Uma venda pode constar nas duas dimensões; não some seus faturamentos.')
    available = sorted(set(base['fisio'].map(team_name)) | set(base['indicador'].map(team_name)))
    defaults = [name for name in TEAM if name in available]
    chosen = st.multiselect('Profissionais a comparar', available, default=defaults or available, key='team_select')
    rows = []
    for name in chosen:
        sold = base[base['fisio_key'] == norm(name)]
        referred = base[base['indicador_key'] == norm(name)]
        ms, mi = metrics(sold), metrics(referred)
        row = {'Fisioterapeuta': name,
               'Vendas fechadas (nº)': ms['vendas'], 'Faturamento vendido (R$)': ms['valor'],
               'Ticket vendas (R$)': ms['ticket'] if ms['vendas'] else None,
               'Indicações geradas (nº)': mi['vendas'], 'Faturamento indicado (R$)': mi['valor'],
               'Ticket indicações (R$)': mi['ticket'] if mi['vendas'] else None,
               'Reabilitações >10 (%)': round(ms['percentual_longo'], 1) if ms['percentual_longo'] is not None else None,
               'Sessões vendidas (informadas)': float(sold['sessoes'].sum()) if sold['sessoes'].notna().any() else None}
        row.update(service_stats(sold, 'Vendas'))
        row.update(service_stats(referred, 'Indicações'))
        rows.append(row)
    comp = pd.DataFrame(rows)
    if comp.empty:
        st.info('Selecione ao menos um profissional.')
    else:
        money_cols = [c for c in comp.columns if '(R$)' in c]
        cfg = {c: st.column_config.NumberColumn(format='R$ %.2f') for c in money_cols}
        cfg['Reabilitações >10 (%)'] = st.column_config.NumberColumn(format='%.1f%%')
        st.dataframe(comp.sort_values('Faturamento vendido (R$)', ascending=False), use_container_width=True,
                     hide_index=True, column_config=cfg)
        ranking_options = [c for c in comp.columns if c not in ('Fisioterapeuta',) and c != 'Sessões vendidas (informadas)']
        ranking_options += ['Sessões vendidas (informadas)']
        ranking = st.selectbox('Ranking por indicador', ranking_options)
        ranked = comp.sort_values(ranking, ascending=False, na_position='last')
        st.plotly_chart(px.bar(ranked, x='Fisioterapeuta', y=ranking, text_auto='.2s',
                               title=f'Ranking — {ranking}'), use_container_width=True)
        comparison = comp.melt(id_vars='Fisioterapeuta',
                               value_vars=['Faturamento vendido (R$)', 'Faturamento indicado (R$)'],
                               var_name='Dimensão', value_name='Faturamento (R$)')
        st.plotly_chart(px.bar(comparison, x='Fisioterapeuta', y='Faturamento (R$)', color='Dimensão',
                               barmode='group', title='Vendas fechadas x indicações geradas'),
                        use_container_width=True)
    st.info('Atendimentos realizados e taxas por 100 atendimentos dependem da aba Base | Atendimentos. Conversão depende do registro dos leads atribuídos.')

with individual:
    st.subheader('Desempenho individual: vendas fechadas e indicações geradas')
    people = sorted(set(df['fisio'].map(team_name)) | set(df['indicador'].map(team_name)))
    initial = next((name for name in TEAM if name in people), people[0])
    selected = st.selectbox('Profissional', people, index=people.index(initial))
    sold = base[base['fisio_key'] == norm(selected)]
    referred = base[base['indicador_key'] == norm(selected)]
    st.caption('Indicadores abaixo respeitam os meses, serviços e origens selecionados na lateral.')
    ms, mi = metrics(sold), metrics(referred)
    left, right = st.columns(2)
    for column, label, stats in [(left, 'VENDAS FECHADAS', ms), (right, 'INDICAÇÕES GERADAS', mi)]:
        with column:
            st.markdown(f'#### {label}')
            st.metric('Faturamento (R$)', brl(stats['valor']))
            a, b = st.columns(2)
            a.metric('Quantidade de vendas', stats['vendas'])
            b.metric('Ticket médio', brl(stats['ticket']) if stats['vendas'] else '—')
    summary = []
    for label, frame in [('Vendas fechadas', sold), ('Indicações geradas', referred)]:
        for category in ['Reabilitação', 'Recovery']:
            part = frame[frame['categoria'] == category]
            summary.append({'Dimensão': label, 'Serviço': category, 'Vendas (nº)': len(part),
                            'Faturamento (R$)': float(part['valor'].sum()),
                            'Ticket médio (R$)': float(part['valor'].mean()) if len(part) else None})
    st.subheader('Quantidade, faturamento e ticket por serviço')
    services_summary = pd.DataFrame(summary)
    st.dataframe(services_summary, use_container_width=True, hide_index=True,
                 column_config={'Faturamento (R$)': st.column_config.NumberColumn(format='R$ %.2f'),
                                'Ticket médio (R$)': st.column_config.NumberColumn(format='R$ %.2f')})
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.bar(services_summary, x='Serviço', y='Vendas (nº)', color='Dimensão',
                               barmode='group', title='Quantidade de vendas por serviço', text_auto=True),
                        use_container_width=True)
    with c2:
        st.plotly_chart(px.bar(services_summary, x='Serviço', y='Faturamento (R$)', color='Dimensão',
                               barmode='group', title='Faturamento por serviço'), use_container_width=True)
    st.subheader('Evolução mensal — vendas x indicações')
    st.caption('Histórico completo com os filtros de serviço e origem; o filtro de meses da lateral não limita este gráfico.')
    historical = df[df['categoria'].isin(selected_services) & df['origem'].isin(selected_origins)].copy()
    sold_h = historical[historical['fisio_key'] == norm(selected)]
    referred_h = historical[historical['indicador_key'] == norm(selected)]
    if sold_h.empty and referred_h.empty:
        st.info('Sem histórico para este profissional nos filtros escolhidos.')
    else:
        first = min([frame['data'].min() for frame in (sold_h, referred_h) if not frame.empty])
        last = historical['data'].max()
        month_range = pd.period_range(first.to_period('M'), last.to_period('M'), freq='M').astype(str).tolist()
        history = pd.concat([month_series(sold_h, month_range, 'Vendas fechadas'),
                             month_series(referred_h, month_range, 'Indicações geradas')], ignore_index=True)
        st.plotly_chart(px.line(history, x='mes', y='faturamento', color='Dimensão', markers=True,
                                labels={'mes': 'Mês', 'faturamento': 'Faturamento (R$)'}),
                        use_container_width=True)
        st.plotly_chart(px.bar(history, x='mes', y='quantidade', color='Dimensão', barmode='group',
                               title='Quantidade mensal de vendas e indicações',
                               labels={'mes': 'Mês', 'quantidade': 'Vendas (nº)'}), use_container_width=True)
        st.dataframe(history.rename(columns={'mes': 'Mês', 'faturamento': 'Faturamento (R$)',
                                             'quantidade': 'Vendas (nº)'}),
                     hide_index=True, use_container_width=True)
        st.caption('Meses sem vendas são exibidos com zero. O último mês pode estar incompleto.')

st.divider()
st.caption('Resultados profissionais compartilhados. Não são exibidos dados pessoais de pacientes. Proteja o acesso ao aplicativo: a URL pública não equivale a controle de acesso.')
