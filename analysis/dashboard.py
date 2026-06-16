import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import os

os.chdir(os.path.expanduser('~/EBP Pipeline'))

st.set_page_config(
    page_title="PT Research Pipeline",
    page_icon="🔬",
    layout="wide"
)

# Load data
@st.cache_data
def load_data():
    df = pd.read_csv('ledger.csv')
    for col in ['relevance_to_pq','implementation_result','appraisal_confidence']:
        if col in df.columns:
            df[col] = df[col].str.strip().str.rstrip('|').str.strip()
    return df

df = load_data()

# Header
st.markdown("""
<div style='background:#0078D4;padding:24px;border-radius:8px;margin-bottom:24px;'>
    <h1 style='color:white;margin:0;font-size:28px;'>PT Research Pipeline</h1>
    <p style='color:rgba(255,255,255,0.8);margin:4px 0 0 0;font-size:14px;'>
        AI & LLM in Physical Therapy — Evidence Synthesis Dashboard
    </p>
</div>
""", unsafe_allow_html=True)

# Top metrics
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Total Appraised", len(df))
with col2:
    st.metric("Grade A", len(df[df['mcdermott_grade']=='A']))
with col3:
    st.metric("High Relevance", len(df[df['relevance_to_pq']=='high']))
with col4:
    st.metric("Level 1a Studies", len(df[df['oxford_level']=='1a']))
with col5:
    st.metric("Implementation Success", len(df[df['implementation_result']=='success']))

st.markdown("---")

# Row 1 charts
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("Evidence Grade Distribution")
    grade_counts = df['mcdermott_grade'].value_counts().reset_index()
    grade_counts.columns = ['Grade','Count']
    grade_counts = grade_counts.sort_values('Grade')
    colors = {'A':'#70AD47','B':'#9DC3E6','C':'#FFC000','D':'#FF6B6B'}
    fig = px.pie(grade_counts, values="Count", names="Grade",
                   color='Grade', color_discrete_map=colors,
                   hole=0.5)
    fig.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=280,
                      legend=dict(orientation='h',y=-0.1))
    fig.update_traces(textinfo='label+percent')
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Relevance to Primary Question")
    rel_counts = df['relevance_to_pq'].value_counts().reset_index()
    rel_counts.columns = ['Relevance','Count']
    rel_order = {'high':0,'moderate':1,'low':2}
    rel_counts['order'] = rel_counts['Relevance'].map(rel_order)
    rel_counts = rel_counts.sort_values('order')
    rel_colors = {'high':'#FF4444','moderate':'#FFC000','low':'#AAAAAA'}
    fig2 = px.bar(rel_counts, x='Count', y='Relevance', orientation='h',
                  color='Relevance', color_discrete_map=rel_colors)
    fig2.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=280,
                       showlegend=False, yaxis_title='')
    fig2.update_traces(texttemplate='%{x}', textposition='outside')
    st.plotly_chart(fig2, use_container_width=True)

with col3:
    st.subheader("Oxford Evidence Level")
    ox_counts = df['oxford_level'].value_counts().reset_index()
    ox_counts.columns = ['Level','Count']
    ox_order = {'1a':0,'1b':1,'1c':2,'2a':3,'2b':4,'2c':5,'3a':6,'3b':7,'4':8,'5':9}
    ox_counts['order'] = ox_counts['Level'].map(ox_order).fillna(10)
    ox_counts = ox_counts.sort_values('order')
    ox_colors = ['#70AD47' if l in ['1a','1b','1c'] else
                 '#9DC3E6' if l in ['2a','2b','2c'] else
                 '#FFC000' if l in ['3a','3b','4'] else '#FF6B6B'
                 for l in ox_counts['Level']]
    fig3 = px.bar(ox_counts, x='Level', y='Count', color='Level',
                  color_discrete_sequence=ox_colors)
    fig3.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=280,
                       showlegend=False, xaxis_title='Oxford Level')
    st.plotly_chart(fig3, use_container_width=True)

st.markdown("---")

# Row 2 - Implementation and Feed
col1, col2 = st.columns(2)

with col1:
    st.subheader("Implementation Results")
    impl_counts = df['implementation_result'].value_counts().reset_index()
    impl_counts.columns = ['Result','Count']
    impl_colors = {'success':'#70AD47','mixed':'#FFC000',
                   'failure':'#FF4444','not_reported':'#AAAAAA'}
    fig4 = px.pie(impl_counts, values='Count', names='Result',
                  color='Result', color_discrete_map=impl_colors)
    fig4.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=260)
    st.plotly_chart(fig4, use_container_width=True)

with col2:
    st.subheader("Feed Source Distribution")
    feed_counts = df['feed_source'].value_counts().reset_index()
    feed_counts.columns = ['Feed','Count']
    feed_counts['Feed'] = feed_counts['Feed'].replace({
        'feed_a_synthesis': 'Feed A — Synthesis',
        'feed_b_implementation': 'Feed B — Implementation',
        'manual': 'Manual'
    })
    fig5 = px.bar(feed_counts, x='Feed', y='Count',
                  color_discrete_sequence=['#0078D4'])
    fig5.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=260,
                       showlegend=False, xaxis_title='')
    st.plotly_chart(fig5, use_container_width=True)

st.markdown("---")

# High relevance articles
st.subheader("🔴 High Relevance Articles")
high = df[df['relevance_to_pq']=='high'].sort_values('oxford_level')

for _, row in high.iterrows():
    grade = row.get('mcdermott_grade','')
    oxford = row.get('oxford_level','')
    grade_color = {'A':'#70AD47','B':'#9DC3E6','C':'#FFC000','D':'#FF6B6B'}.get(grade,'#AAAAAA')

    with st.expander(f"**{row.get('title','')[:90]}**  |  Oxford {oxford} / Grade {grade}"):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"**PMID:** {row.get('pmid','')}")
            st.markdown(f"**Journal:** {row.get('journal','')}")
        with col2:
            st.markdown(f"**Year:** {row.get('publication_year','')}")
            st.markdown(f"**Feed:** {row.get('feed_source','')}")
        with col3:
            st.markdown(f"**Implementation:** {row.get('implementation_result','')}")
            st.markdown(f"**Confidence:** {row.get('appraisal_confidence','')}")
        with col4:
            st.markdown(f"[View on PubMed](https://pubmed.ncbi.nlm.nih.gov/{row.get('pmid','')})")

        st.markdown("**Clinician Summary:**")
        st.info(row.get('clinician_summary','Not available'))

        gov = row.get('governance_recs','')
        if gov and gov.lower() not in ('none stated','none','nan',''):
            st.markdown("**Governance Recommendations:**")
            st.warning(gov)

st.markdown("---")

# Full article table with filters
st.subheader("Full Evidence Base")

col1, col2, col3 = st.columns(3)
with col1:
    grade_filter = st.multiselect("Filter by Grade",
        options=['A','B','C','D'], default=['A','B','C','D'])
with col2:
    rel_filter = st.multiselect("Filter by Relevance",
        options=['high','moderate','low'], default=['high','moderate','low'])
with col3:
    search = st.text_input("Search titles")

filtered = df[
    df['mcdermott_grade'].isin(grade_filter) &
    df['relevance_to_pq'].isin(rel_filter)
]
if search:
    filtered = filtered[filtered['title'].str.contains(search, case=False, na=False)]

st.dataframe(
    filtered[['pmid','title','oxford_level','mcdermott_grade',
              'relevance_to_pq','implementation_result','journal','publication_year']].rename(columns={
        'pmid':'PMID','title':'Title','oxford_level':'Oxford',
        'mcdermott_grade':'Grade','relevance_to_pq':'Relevance',
        'implementation_result':'Implementation','journal':'Journal',
        'publication_year':'Year'
    }),
    use_container_width=True,
    height=400
)

st.caption(f"PT Research Pipeline · {len(df)} articles appraised · Llama 3 via Ollama · Evidence grades should be verified by a qualified clinician before clinical application.")
