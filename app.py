import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import base64

# ================= 配置与初始化 =================
st.set_page_config(page_title="Invoicer Pro (Cloud Sync)", layout="wide", page_icon="☁️")

# 1. 建立 Google Sheets 连接
# 这里的 "gsheets" 对应您在 secrets.toml 里写的 [connections.gsheets]
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("⚠️ 连接 Google Sheets 失败，请检查 Secrets 配置。")
    st.stop()

# 2. 从云端读取数据 (核心修改：使用 ttl=0 强制不缓存，确保中法同步)
try:
    df_clients = conn.read(worksheet="clients", ttl=0)
    df_products = conn.read(worksheet="products", ttl=0)
    df_invoices = conn.read(worksheet="invoices", ttl=0)
    
    # 防止空表报错，确保数据类型正确
    if df_clients.empty:
        df_clients = pd.DataFrame(columns=["ID", "Name", "Address", "Zone", "VAT"])
    if df_products.empty:
        df_products = pd.DataFrame(columns=["SKU", "Desc", "Price"])
    if df_invoices.empty:
        df_invoices = pd.DataFrame(columns=["InvoiceNo", "Date", "Client", "Total_HT", "Total_TTC", "Status"])
        
except Exception as e:
    st.error(f"⚠️ 读取数据失败，请确保您的 Google Sheet 里有 clients, products, invoices 这三个工作表。\n错误信息: {e}")
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

# ================= 页面 1: 创建发票 (核心功能) =================
if menu == "📝 创建发票":
    st.title("创建新发票 / New Invoice")
    
    # 自动生成编号 (基于云端已有数量)
    next_num = len(df_invoices) + 1
    default_inv_no = f"FAC-{datetime.now().year}-{next_num:03d}"
    
    col1, col2 = st.columns(2)
    with col1:
        inv_no = st.text_input("发票编号 (Invoice No)", value=default_inv_no)
    with col2:
        inv_date = st.date_input("日期 (Date)", datetime.now())

    # 选择客户 (数据源：df_clients)
    if df_clients.empty:
        st.warning("⚠️ 客户库为空，请先去【客户管理】添加客户。")
        st.stop()
        
    client_list = df_clients['Name'].tolist()
    selected_client_name = st.selectbox("选择客户 (Client)", client_list)
    
    # 获取客户详情
    client_data = df_clients[df_clients['Name'] == selected_client_name].iloc[0]
    
    st.info(f"📍 客户区域: **{client_data['Zone']}** | 税号: {client_data['VAT']}")
    
    # --- 自动合规逻辑 ---
    tva_rate = 0.0
    legal_text = ""
    if client_data['Zone'] == "France":
        tva_rate = 0.20
        legal_text = "TVA applicable 20%."
    elif client_data['Zone'] == "UE":
        tva_rate = 0.0
        legal_text = "Exonération de TVA, article 262 ter, I du CGI (Autoliquidation)."
    else: # Export
        tva_rate = 0.0
        legal_text = "Exonération de TVA, article 262 I du CGI (Exportation)."
    
    st.caption(f"⚖️ 法律条款: {legal_text}")

    st.divider()
    
    # 购物车 (Cart) 仍然可以使用 session_state，因为它是临时的，还没保存
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
        
        # 保存与生成 PDF (核心修改：写入云端)
        if st.button("✅ 确认开票 (同步到云端)", type="primary"):
            # 1. 准备新数据
            new_inv = pd.DataFrame([{
                "InvoiceNo": inv_no,
                "Date": str(inv_date),
                "Client": selected_client_name,
                "Total_HT": total_ht,
                "Total_TTC": total_ttc,
                "Status": "Sent"
            }])
            
            # 2. 读取最新云端数据并合并 (防止覆盖他人刚开的票)
            current_invoices_cloud = conn.read(worksheet="invoices", ttl=0)
            updated_df = pd.concat([current_invoices_cloud, new_inv], ignore_index=True)
            
            # 3. 写入 Google Sheets
            conn.update(worksheet="invoices", data=updated_df)
            
            # 4. 生成 PDF
            pdf_bytes = create_pdf({
                "no": inv_no, "date": inv_date, 
                "client_name": selected_client_name, "client_addr": client_data['Address'], "client_vat": client_data['VAT'],
                "tva_rate": tva_rate, "legal_text": legal_text
            }, st.session_state['cart'])
            
            # 5. 提供下载
            b64 = base64.b64encode(pdf_bytes).decode()
            href = f'<a href="data:application/octet-stream;base64,{b64}" download="{inv_no}.pdf">📥 点击下载 PDF 发票</a>'
            st.markdown(href, unsafe_allow_html=True)
            st.success("🎉 开票成功！数据已同步到 Google Sheets，中国和法国团队均可见。")
            
            # 清空购物车
            st.session_state['cart'] = pd.DataFrame(columns=["SKU", "Desc", "Price", "Quantity"])
            st.cache_data.clear() # 清除缓存以便立刻看到更新

# ================= 页面 2: 仪表盘 =================
elif menu == "📊 仪表盘":
    st.title("业务概览 (实时云端数据)")
    
    # 确保读取的是最新的
    df = df_invoices 
    
    if df.empty:
        st.warning("暂无发票数据")
    else:
        k1, k2, k3 = st.columns(3)
        k1.metric("总营收 (HT)", f"€ {df['Total_HT'].sum():.2f}")
        k2.metric("开票数量", len(df))
        k3.metric("平均单价", f"€ {df['Total_HT'].mean():.2f}")
        
        st.subheader("发票记录")
        st.dataframe(df, use_container_width=True)
        
        # 简单图表
        if not df.empty and 'Total_HT' in df.columns:
             st.bar_chart(df, x="Date", y="Total_HT")

# ================= 页面 3: 客户管理 =================
elif menu == "👥 客户管理":
    st.title("客户数据库")
    st.caption("修改下方表格后，请务必点击【保存更改】按钮。")
    
    # 可编辑表格
    edited_clients = st.data_editor(df_clients, num_rows="dynamic", use_container_width=True)
    
    if st.button("💾 保存客户变更"):
        conn.update(worksheet="clients", data=edited_clients)
        st.success("客户数据已更新并同步到云端！")
        st.cache_data.clear()

# ================= 页面 4: 产品库 =================
elif menu == "📦 产品库":
    st.title("产品管理")
    st.caption("修改下方表格后，请务必点击【保存更改】按钮。")
    
    edited_products = st.data_editor(df_products, num_rows="dynamic", use_container_width=True)
    
    if st.button("💾 保存产品变更"):
        conn.update(worksheet="products", data=edited_products)
        st.success("产品数据已更新并同步到云端！")
        st.cache_data.clear()
