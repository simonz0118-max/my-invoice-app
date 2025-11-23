import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import base64

# ================= 配置与初始化 =================
st.set_page_config(page_title="Invoicer Pro (France)", layout="wide", page_icon="💶")

# 初始化 Session State (模拟数据库)
if 'clients' not in st.session_state:
    st.session_state['clients'] = pd.DataFrame([
        {"ID": "C001", "Name": "US Trading Corp", "Address": "NY, USA", "Zone": "Export", "VAT": "-"},
        {"ID": "C002", "Name": "Berlin Shop Gmbh", "Address": "Berlin, DE", "Zone": "UE", "VAT": "DE123456789"},
        {"ID": "C003", "Name": "Local Paris SAS", "Address": "Paris, FR", "Zone": "France", "VAT": "FR99887766"},
    ])

if 'products' not in st.session_state:
    st.session_state['products'] = pd.DataFrame([
        {"SKU": "P001", "Desc": "Tibetan Bracelet / Bracelet", "Price": 50.0},
        {"SKU": "P002", "Desc": "Thangka / Peinture", "Price": 200.0},
    ])

if 'invoices' not in st.session_state:
    st.session_state['invoices'] = pd.DataFrame(columns=["InvoiceNo", "Date", "Client", "Total_HT", "Total_TTC", "Status"])

# ================= 工具函数：PDF 生成 =================
def create_pdf(invoice_data, items_df):
    pdf = FPDF()
    pdf.add_page()
    
    # 字体设置 (不支持中文需额外加载字体，这里演示用英文/法文)
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "COMMERCIAL INVOICE / FACTURE", 0, 1, 'C')
    
    pdf.set_font("Arial", '', 10)
    
    # 公司信息 (卖方)
    pdf.ln(10)
    pdf.cell(100, 5, "ISSUER: My French Trading SAS", 0, 0)
    pdf.cell(90, 5, f"NO: {invoice_data['no']}", 0, 1, 'R')
    pdf.cell(100, 5, "Address: 123 Rue de la Loi, Paris", 0, 0)
    pdf.cell(90, 5, f"DATE: {invoice_data['date']}", 0, 1, 'R')
    pdf.cell(100, 5, "SIRET: 888 999 000 | VAT: FR12888...", 0, 1)
    
    pdf.ln(10)
    # 客户信息
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(0, 5, f"TO: {invoice_data['client_name']}", 0, 1)
    pdf.set_font("Arial", '', 10)
    pdf.cell(0, 5, f"Address: {invoice_data['client_addr']}", 0, 1)
    pdf.cell(0, 5, f"Client VAT: {invoice_data['client_vat']}", 0, 1)
    
    # 表格头
    pdf.ln(10)
    pdf.set_fill_color(200, 220, 255)
    pdf.cell(30, 8, "SKU", 1, 0, 'C', True)
    pdf.cell(80, 8, "Description", 1, 0, 'C', True)
    pdf.cell(20, 8, "Qty", 1, 0, 'C', True)
    pdf.cell(30, 8, "Unit Price", 1, 0, 'C', True)
    pdf.cell(30, 8, "Total", 1, 1, 'C', True)
    
    # 商品内容
    total_ht = 0
    for idx, row in items_df.iterrows():
        line_total = row['Quantity'] * row['Price']
        total_ht += line_total
        pdf.cell(30, 8, str(row['SKU']), 1)
        pdf.cell(80, 8, str(row['Desc']), 1)
        pdf.cell(20, 8, str(row['Quantity']), 1, 0, 'C')
        pdf.cell(30, 8, f"{row['Price']:.2f}", 1, 0, 'R')
        pdf.cell(30, 8, f"{line_total:.2f}", 1, 1, 'R')
        
    # 计算税额
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
    
    # 法律条款
    pdf.ln(10)
    pdf.set_font("Arial", 'I', 9)
    pdf.multi_cell(0, 5, f"Mentions Legales: {invoice_data['legal_text']}")
    pdf.ln(2)
    pdf.multi_cell(0, 5, "Payment Terms: No discount. Late penalty: 3x interest rate. Recovery fee: 40 EUR.")
    
    return pdf.output(dest='S').encode('latin-1')

# ================= 侧边栏导航 =================
menu = st.sidebar.radio("功能导航", ["📝 创建发票", "📊 仪表盘", "👥 客户管理", "📦 产品库"])

# ================= 页面 1: 创建发票 (核心功能) =================
if menu == "📝 创建发票":
    st.title("创建新发票 / New Invoice")
    
    col1, col2 = st.columns(2)
    with col1:
        inv_no = st.text_input("发票编号 (Invoice No)", value=f"FAC-{datetime.now().year}-{len(st.session_state['invoices'])+1:03d}")
    with col2:
        inv_date = st.date_input("日期 (Date)", datetime.now())

    # 选择客户
    client_list = st.session_state['clients']['Name'].tolist()
    selected_client_name = st.selectbox("选择客户 (Client)", client_list)
    
    # 获取客户详情用于逻辑判断
    client_data = st.session_state['clients'][st.session_state['clients']['Name'] == selected_client_name].iloc[0]
    
    st.info(f"📍 客户区域: **{client_data['Zone']}** | 税号: {client_data['VAT']}")
    
    # --- 自动合规逻辑 ---
    tva_rate = 0.0
    legal_text = ""
    
    if client_data['Zone'] == "France":
        tva_rate = 0.20
        legal_text = "TVA applicable 20%."
    elif client_data['Zone'] == "UE":
        tva_rate = 0.0
        legal_text = "Exonération de TVA, article 262 ter, I du CGI (Autoliquidation / Reverse Charge)."
    else: # Export
        tva_rate = 0.0
        legal_text = "Exonération de TVA, article 262 I du CGI (Exportation)."
    
    st.caption(f"⚖️ 法律条款自动生成: {legal_text}")
    # -------------------

    st.divider()
    
    # 添加商品 (简单模拟)
    st.subheader("商品明细")
    
    if 'cart' not in st.session_state:
        st.session_state['cart'] = pd.DataFrame(columns=["SKU", "Desc", "Price", "Quantity"])

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        prod_select = st.selectbox("选择产品", st.session_state['products']['Desc'])
    with c2:
        qty = st.number_input("数量", min_value=1, value=1)
    with c3:
        if st.button("➕ 添加到列表"):
            prod_info = st.session_state['products'][st.session_state['products']['Desc'] == prod_select].iloc[0]
            new_row = {"SKU": prod_info['SKU'], "Desc": prod_info['Desc'], "Price": prod_info['Price'], "Quantity": qty}
            st.session_state['cart'] = pd.concat([st.session_state['cart'], pd.DataFrame([new_row])], ignore_index=True)

    # 显示购物车
    if not st.session_state['cart'].empty:
        st.dataframe(st.session_state['cart'], use_container_width=True)
        
        # 计算总额
        total_ht = (st.session_state['cart']['Price'] * st.session_state['cart']['Quantity']).sum()
        total_tva = total_ht * tva_rate
        total_ttc = total_ht + total_tva
        
        c_tot1, c_tot2, c_tot3 = st.columns(3)
        c_tot1.metric("Total HT", f"€ {total_ht:.2f}")
        c_tot2.metric(f"TVA ({tva_rate*100}%)", f"€ {total_tva:.2f}")
        c_tot3.metric("Total TTC", f"€ {total_ttc:.2f}")
        
        # 保存与生成 PDF
        if st.button("✅ 确认开票并生成 PDF", type="primary"):
            # 1. 保存到历史记录
            new_inv = {
                "InvoiceNo": inv_no,
                "Date": inv_date,
                "Client": selected_client_name,
                "Total_HT": total_ht,
                "Total_TTC": total_ttc,
                "Status": "Sent"
            }
            st.session_state['invoices'] = pd.concat([st.session_state['invoices'], pd.DataFrame([new_inv])], ignore_index=True)
            
            # 2. 生成 PDF
            pdf_bytes = create_pdf({
                "no": inv_no, "date": inv_date, 
                "client_name": selected_client_name, "client_addr": client_data['Address'], "client_vat": client_data['VAT'],
                "tva_rate": tva_rate, "legal_text": legal_text
            }, st.session_state['cart'])
            
            # 3. 提供下载
            b64 = base64.b64encode(pdf_bytes).decode()
            href = f'<a href="data:application/octet-stream;base64,{b64}" download="{inv_no}.pdf">📥 点击下载 PDF 发票</a>'
            st.markdown(href, unsafe_allow_html=True)
            st.success("发票已生成并保存！")
            
            # 清空购物车
            st.session_state['cart'] = pd.DataFrame(columns=["SKU", "Desc", "Price", "Quantity"])

# ================= 页面 2: 仪表盘 =================
elif menu == "📊 仪表盘":
    st.title("业务概览")
    if st.session_state['invoices'].empty:
        st.warning("暂无发票数据")
    else:
        df = st.session_state['invoices']
        
        # KPI
        k1, k2, k3 = st.columns(3)
        k1.metric("总营收 (HT)", f"€ {df['Total_HT'].sum():.2f}")
        k2.metric("开票数量", len(df))
        k3.metric("平均单价", f"€ {df['Total_HT'].mean():.2f}")
        
        # 图表
        st.subheader("近期发票记录")
        st.dataframe(df, use_container_width=True)
        
        st.subheader("销售趋势")
        st.bar_chart(df, x="Date", y="Total_HT")

# ================= 页面 3: 客户管理 =================
elif menu == "👥 客户管理":
    st.title("客户数据库")
    edited_df = st.data_editor(st.session_state['clients'], num_rows="dynamic")
    st.session_state['clients'] = edited_df
    st.caption("可以直接在表格中修改、添加或删除客户。Zone 请严格填写: France, UE, 或 Export")

# ================= 页面 4: 产品库 =================
elif menu == "📦 产品库":
    st.title("产品管理")
    edited_prod = st.data_editor(st.session_state['products'], num_rows="dynamic")
    st.session_state['products'] = edited_prod