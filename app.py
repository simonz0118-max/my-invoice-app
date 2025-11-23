import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import base64

# ================= 配置与初始化 =================
st.set_page_config(page_title="Invoicer Pro (Anti-Quota)", layout="wide", page_icon="🛡️")

# 1. 建立连接
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("⚠️ 连接 Google Sheets 失败，请检查 Secrets 配置。")
    st.stop()

# ================= 核心修复：带缓存的数据读取函数 =================
# 使用 @st.cache_data 装饰器，把数据存在内存里，默认 10 分钟(600秒)才过期
# 这样无论你怎么点按钮，都不会消耗 Google API 额度，除非过期或手动刷新
@st.cache_data(ttl=600)
def load_data_from_google():
    # 这里的 ttl=0 是为了在函数执行时强制拿最新，但函数本身被缓存了，所以不会频繁执行
    try:
        clients = conn.read(worksheet="clients", ttl=0)
        products = conn.read(worksheet="products", ttl=0)
        invoices = conn.read(worksheet="invoices", ttl=0)
        return clients, products, invoices
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# 侧边栏增加一个手动刷新按钮
st.sidebar.title("数据同步")
if st.sidebar.button("🔄 立即刷新云端数据"):
    st.cache_data.clear() # 清除缓存
    st.rerun() # 重新运行

# 加载数据 (优先从缓存读)
try:
    df_clients, df_products, df_invoices = load_data_from_google()
    
    # 数据清洗：防止空表报错
    if df_clients.empty:
        df_clients = pd.DataFrame(columns=["ID", "Name", "Address", "Zone", "VAT"])
    if df_products.empty:
        df_products = pd.DataFrame(columns=["SKU", "Desc", "Price"])
    if df_invoices.empty:
        df_invoices = pd.DataFrame(columns=["InvoiceNo", "Date", "Client", "Total_HT", "Total_TTC", "Status"])
except Exception as e:
    st.error(f"⚠️ 数据加载因配额限制暂停，请等待1分钟后再试。\n错误信息: {e}")
    st.stop()

# ================= 工具函数：PDF 生成 (保持不变) =================
def create_pdf(invoice_data, items_df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "COMMERCIAL INVOICE / FACTURE", 0, 1, 'C')
    pdf.set_font("Arial", '', 10)
    
    pdf.ln(10)
    pdf.cell(100, 5, "ISSUER: My French Trading SAS", 0, 0)
    pdf.cell(90, 5, f"NO: {invoice_data['no']}", 0, 1, 'R')
    pdf.cell(100, 5, "Address: 123 Rue de la Loi, Paris", 0, 0)
    pdf.cell(90, 5, f"DATE: {invoice_data['date']}", 0, 1, 'R')
    pdf.cell(100, 5, "SIRET: 888 999 000 | VAT: FR12888...", 0, 1)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(0, 5, f"TO: {invoice_data['client_name']}", 0, 1)
    pdf.set_font("Arial", '', 10)
    pdf.cell(0, 5, f"Address: {invoice_data['client_addr']}", 0, 1)
    pdf.cell(0, 5, f"Client VAT: {invoice_data['client_vat']}", 0, 1)
    
    pdf.ln(10)
    pdf.set_fill_color(200, 220, 255)
    pdf.cell(30, 8, "SKU", 1, 0, 'C', True)
    pdf.cell(80, 8, "Description", 1, 0, 'C', True)
    pdf.cell(20, 8, "Qty", 1, 0, 'C', True)
    pdf.cell(30, 8, "Unit Price", 1, 0, 'C', True)
    pdf.cell(30, 8, "Total", 1, 1, 'C', True)
    
    total_ht = 0
    for idx, row in items_df.iterrows():
        line_total = row['Quantity'] * row['Price']
        total_ht += line_total
        pdf.cell(30, 8, str(row['SKU']), 1)
        pdf.cell(80, 8, str(row['Desc']), 1)
        pdf.cell(20, 8, str(row['Quantity']), 1, 0, 'C')
        pdf.cell(30, 8, f"{row['Price']:.2f}", 1, 0, 'R')
        pdf.cell(30, 8, f"{line_total:.2f}", 1, 1, 'R')
        
    tva_rate = invoice_data['tva_rate']
    total_tva = total_ht * tva_rate
    total_ttc = total_ht + total_tva
    
    pdf.ln(5)
    pdf.cell(130, 8, "", 0)
    pdf.cell(30, 8, "Total HT:", 1)
    pdf.cell(30, 8, f"{total_ht:.2f} EUR", 1, 1, 'R')
    pdf.cell(130, 8, "", 0)
    pdf.cell(30, 8, f"TVA ({tva_rate*100}%):", 1)
    pdf.cell(30, 8, f"{total_tva:.2f} EUR", 1, 1, 'R')
    pdf.cell(130, 8, "", 0)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(30, 8, "Total TTC:", 1)
    pdf.cell(30, 8, f"{total_ttc:.2f} EUR", 1, 1, 'R')
    
    pdf.ln(10)
    pdf.set_font("Arial", 'I', 9)
    pdf.multi_cell(0, 5, f"Mentions Legales: {invoice_data['legal_text']}")
    
    return pdf.output(dest='S').encode('latin-1')

# ================= 侧边栏导航 =================
menu = st.sidebar.radio("功能导航", ["📝 创建发票", "📊 仪表盘", "👥 客户管理", "📦 产品库"])

# ================= 页面 1: 创建发票 =================
if menu == "📝 创建发票":
    st.title("创建新发票 / New Invoice")
    
    # 自动生成编号 (基于缓存的长度)
    next_num = len(df_invoices) + 1
    default_inv_no = f"FAC-{datetime.now().year}-{next_num:03d}"
    
    col1, col2 = st.columns(2)
    with col1:
        inv_no = st.text_input("发票编号", value=default_inv_no)
    with col2:
        inv_date = st.date_input("日期", datetime.now())

    if df_clients.empty:
        st.warning("⚠️ 客户库为空，请先去【客户管理】添加客户。")
        st.stop()
        
    client_list = df_clients['Name'].tolist()
    selected_client_name = st.selectbox("选择客户", client_list)
    
    client_data = df_clients[df_clients['Name'] == selected_client_name].iloc[0]
    st.info(f"📍 区域: **{client_data['Zone']}** | 税号: {client_data['VAT']}")
    
    # 税法逻辑
    tva_rate = 0.0
    legal_text = ""
    if client_data['Zone'] == "France":
        tva_rate = 0.20
        legal_text = "TVA applicable 20%."
    elif client_data['Zone'] == "UE":
        tva_rate = 0.0
        legal_text = "Exonération de TVA, article 262 ter, I du CGI (Autoliquidation)."
    else: 
        tva_rate = 0.0
        legal_text = "Exonération de TVA, article 262 I du CGI (Exportation)."
    
    st.caption(f"⚖️ 法律条款: {legal_text}")
    st.divider()
    
    # 购物车 (使用 session_state 本地存储)
    if 'cart' not in st.session_state:
        st.session_state['cart'] = pd.DataFrame(columns=["SKU", "Desc", "Price", "Quantity"])

    st.subheader("商品明细")
    if df_products.empty:
        st.warning("请先去【产品库】添加产品。")
    else:
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            prod_select = st.selectbox("选择产品", df_products['Desc'])
        with c2:
            qty = st.number_input("数量", min_value=1, value=1)
        with c3:
            if st.button("➕ 添加"):
                prod_info = df_products[df_products['Desc'] == prod_select].iloc[0]
                new_row = {"SKU": prod_info['SKU'], "Desc": prod_info['Desc'], "Price": prod_info['Price'], "Quantity": qty}
                st.session_state['cart'] = pd.concat([st.session_state['cart'], pd.DataFrame([new_row])], ignore_index=True)

    if not st.session_state['cart'].empty:
        st.dataframe(st.session_state['cart'], use_container_width=True)
        
        total_ht = (st.session_state['cart']['Price'] * st.session_state['cart']['Quantity']).sum()
        total_tva = total_ht * tva_rate
        total_ttc = total_ht + total_tva
        
        c_tot1, c_tot2, c_tot3 = st.columns(3)
        c_tot1.metric("Total HT", f"€ {total_ht:.2f}")
        c_tot2.metric(f"TVA", f"€ {total_tva:.2f}")
        c_tot3.metric("Total TTC", f"€ {total_ttc:.2f}")
        
        # 写入逻辑：仅在点击时调用 API
        if st.button("✅ 确认开票 (同步到云端)", type="primary"):
            try:
                # 1. 准备新数据
                new_inv = pd.DataFrame([{
                    "InvoiceNo": inv_no,
                    "Date": str(inv_date),
                    "Client": selected_client_name,
                    "Total_HT": total_ht,
                    "Total_TTC": total_ttc,
                    "Status": "Sent"
                }])
                
                # 2. 读取云端最新 (只在这时候读一次)
                current_invoices_cloud = conn.read(worksheet="invoices", ttl=0)
                updated_df = pd.concat([current_invoices_cloud, new_inv], ignore_index=True)
                
                # 3. 写入
                conn.update(worksheet="invoices", data=updated_df)
                
                # 4. 生成 PDF
                pdf_bytes = create_pdf({
                    "no": inv_no, "date": inv_date, 
                    "client_name": selected_client_name, "client_addr": client_data['Address'], "client_vat": client_data['VAT'],
                    "tva_rate": tva_rate, "legal_text": legal_text
                }, st.session_state['cart'])
                
                # 5. 关键：清除缓存，确保下次读取是新的
                st.cache_data.clear()
                
                # 6. 下载链接
                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/octet-stream;base64,{b64}" download="{inv_no}.pdf">📥 点击下载 PDF 发票</a>'
                st.markdown(href, unsafe_allow_html=True)
                st.success("🎉 开票成功！云端已更新。")
                
                # 清空购物车
                st.session_state['cart'] = pd.DataFrame(columns=["SKU", "Desc", "Price", "Quantity"])
                
            except Exception as e:
                st.error(f"写入失败，请重试。错误: {e}")

# ================= 页面 2: 仪表盘 =================
elif menu == "📊 仪表盘":
    st.title("业务概览")
    df = df_invoices # 直接用缓存的数据
    
    if df.empty:
        st.warning("暂无数据，请先开一张发票。")
    else:
        k1, k2, k3 = st.columns(3)
        k1.metric("总营收 (HT)", f"€ {df['Total_HT'].sum():.2f}")
        k2.metric("开票数量", len(df))
        k3.metric("平均单价", f"€ {df['Total_HT'].mean():.2f}")
        st.dataframe(df, use_container_width=True)

# ================= 页面 3 & 4 (编辑功能) =================
elif menu == "👥 客户管理":
    st
