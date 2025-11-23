import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import base64

# ================= 配置与初始化 =================
st.set_page_config(page_title="Invoicer Pro (Editable)", layout="wide", page_icon="✏️")

# 1. 建立连接
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("⚠️ 连接 Google Sheets 失败，请检查 Secrets 配置。")
    st.stop()

# ================= 核心：带缓存的数据读取 (防熔断) =================
@st.cache_data(ttl=600)
def load_data_from_google():
    try:
        clients = conn.read(worksheet="clients", ttl=0)
        products = conn.read(worksheet="products", ttl=0)
        invoices = conn.read(worksheet="invoices", ttl=0)
        return clients, products, invoices
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# 侧边栏：刷新按钮
st.sidebar.title("系统操作")
if st.sidebar.button("🔄 刷新/同步数据"):
    st.cache_data.clear()
    st.rerun()

# 加载数据
try:
    df_clients, df_products, df_invoices = load_data_from_google()
    
    # 数据清洗
    if df_clients.empty:
        df_clients = pd.DataFrame(columns=["ID", "Name", "Address", "Zone", "VAT"])
    if df_products.empty:
        df_products = pd.DataFrame(columns=["SKU", "Desc", "Price"])
    if df_invoices.empty:
        df_invoices = pd.DataFrame(columns=["InvoiceNo", "Date", "Client", "Total_HT", "Total_TTC", "Status"])
except Exception as e:
    st.error(f"⚠️ 数据加载暂停 (API限流)，请稍后刷新。\n错误信息: {e}")
    st.stop()

# ================= 工具函数：PDF 生成 =================
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
        
    tva_rate = invoice_data['tva_rate'] # 这里的 rate 已经是小数了 (如 0.20)
    total_tva = total_ht * tva_rate
    total_ttc = total_ht + total_tva
    
    pdf.ln(5)
    pdf.cell(130, 8, "", 0)
    pdf.cell(30, 8, "Total HT:", 1)
    pdf.cell(30, 8, f"{total_ht:.2f} EUR", 1, 1, 'R')
    pdf.cell(130, 8, "", 0)
    pdf.cell(30, 8, f"TVA ({tva_rate*100:.1f}%):", 1) # 显示小数点后一位
    pdf.cell(30, 8, f"{total_tva:.2f} EUR", 1, 1, 'R')
    pdf.cell(130, 8, "", 0)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(30, 8, "Total TTC:", 1)
    pdf.cell(30, 8, f"{total_ttc:.2f} EUR", 1, 1, 'R')
    
    pdf.ln(10)
    pdf.set_font("Arial", 'I', 9)
    # 处理多行法律条款，防止乱码
    legal_text = invoice_data['legal_text'].encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 5, f"Mentions Legales: {legal_text}")
    
    return pdf.output(dest='S').encode('latin-1')

# ================= 侧边栏导航 =================
menu = st.sidebar.radio("功能导航", ["📝 创建发票", "📊 仪表盘", "👥 客户管理", "📦 产品库"])

# ================= 页面 1: 创建发票 (已升级) =================
if menu == "📝 创建发票":
    st.title("创建新发票 / New Invoice")
    
    next_num = len(df_invoices) + 1
    default_inv_no = f"FAC-{datetime.now().year}-{next_num:03d}"
    
    # 第一行：编号与日期
    c_info1, c_info2 = st.columns(2)
    with c_info1:
        inv_no = st.text_input("发票编号", value=default_inv_no)
    with c_info2:
        inv_date = st.date_input("日期", datetime.now())

    if df_clients.empty:
        st.warning("⚠️ 客户库为空，请先去【客户管理】添加客户。")
        st.stop()
        
    # 第二行：选择客户
    client_list = df_clients['Name'].tolist()
    selected_client_name = st.selectbox("选择客户", client_list)
    
    client_data = df_clients[df_clients['Name'] == selected_client_name].iloc[0]
    st.info(f"📍 区域: **{client_data['Zone']}** | 税号: {client_data['VAT']}")
    
    # === ✨ 新增功能：智能默认值 + 自由编辑 ===
    # 1. 先计算“建议值”
    default_rate_val = 0.0
    default_legal_text = ""
    
    if client_data['Zone'] == "France":
        default_rate_val = 20.0 # 百分比
        default_legal_text = "TVA applicable 20%."
    elif client_data['Zone'] == "UE":
        default_rate_val = 0.0
        default_legal_text = "Exonération de TVA, article 262 ter, I du CGI (Autoliquidation)."
    else: 
        default_rate_val = 0.0
        default_legal_text = "Exonération de TVA, article 262 I du CGI (Exportation)."
    
    # 2. 提供输入框让用户覆盖 (Key非常重要，用于重置)
    st.markdown("### ⚙️ 税务设置 (可自由修改)")
    c_tax1, c_tax2 = st.columns([1, 3])
    
    with c_tax1:
        # 税率输入框 (单位是 %)
        user_tva_percent = st.number_input("TVA 税率 (%)", 
                                           min_value=0.0, 
                                           max_value=100.0, 
                                           value=default_rate_val,
                                           step=0.1,
                                           format="%.1f")
    
    with c_tax2:
        # 法律条款输入框 (文本域)
        user_legal_text = st.text_area("法律条款 / Mentions Légales", 
                                       value=default_legal_text, 
                                       height=68)

    st.divider()
    
    # === 购物车逻辑 ===
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
        
        # 计算金额 (使用用户输入的税率)
        real_tva_rate = user_tva_percent / 100.0
        
        total_ht = (st.session_state['cart']['Price'] * st.session_state['cart']['Quantity']).sum()
        total_tva = total_ht * real_tva_rate
        total_ttc = total_ht + total_tva
        
        c_tot1, c_tot2, c_tot3 = st.columns(3)
        c_tot1.metric("Total HT", f"€ {total_ht:.2f}")
        c_tot2.metric(f"TVA ({user_tva_percent}%)", f"€ {total_tva:.2f}")
        c_tot3.metric("Total TTC", f"€ {total_ttc:.2f}")
        
        # 写入与生成
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
                
                # 2. 读取云端
                current_invoices_cloud = conn.read(worksheet="invoices", ttl=0)
                updated_df = pd.concat([current_invoices_cloud, new_inv], ignore_index=True)
                
                # 3. 写入
                conn.update(worksheet="invoices", data=updated_df)
                
                # 4. 生成 PDF (传入用户自定义的 税率 和 条款)
                pdf_bytes = create_pdf({
                    "no": inv_no, "date": inv_date, 
                    "client_name": selected_client_name, "client_addr": client_data['Address'], "client_vat": client_data['VAT'],
                    "tva_rate": real_tva_rate,      # <--- 使用自定义税率
                    "legal_text": user_legal_text   # <--- 使用自定义条款
                }, st.session_state['cart'])
                
                st.cache_data.clear()
                
                # 5. 下载
                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/octet-stream;base64,{b64}" download="{inv_no}.pdf">📥 点击下载 PDF 发票</a>'
                st.markdown(href, unsafe_allow_html=True)
                st.success("🎉 开票成功！云端已更新。")
                
                st.session_state['cart'] = pd.DataFrame(columns=["SKU", "Desc", "Price", "Quantity"])
                
            except Exception as e:
                st.error(f"写入失败，请重试。错误: {e}")

# ================= 页面 2: 仪表盘 =================
elif menu == "📊 仪表盘":
    st.title("业务概览")
    df = df_invoices
    if df.empty:
        st.warning("暂无数据。")
    else:
        k1, k2, k3 = st.columns(3)
        k1.metric("总营收 (HT)", f"€ {df['Total_HT'].sum():.2f}")
        k2.metric("开票数量", len(df))
        k3.metric("平均单价", f"€ {df['Total_HT'].mean():.2f}")
        st.dataframe(df, use_container_width=True)

# ================= 页面 3 & 4 (编辑功能) =================
elif menu == "👥 客户管理":
    st.title("客户数据库")
    edited_clients = st.data_editor(df_clients, num_rows="dynamic", use_container_width=True)
    if st.button("💾 保存客户变更"):
        conn.update(worksheet="clients", data=edited_clients)
        st.cache_data.clear()
        st.success("已保存！")

elif menu == "📦 产品库":
    st.title("产品管理")
    edited_products = st.data_editor(df_products, num_rows="dynamic", use_container_width=True)
    if st.button("💾 保存产品变更"):
        conn.update(worksheet="products", data=edited_products)
        st.cache_data.clear()
        st.success("已保存！")
