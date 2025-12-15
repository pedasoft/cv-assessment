import streamlit as st
import pandas as pd
import openai
from imap_tools import MailBox, AND
import PyPDF2
from docx import Document
import io
import json

# --- Yardımcı Fonksiyonlar ---

def extract_text_from_pdf(file_bytes):
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        return f"PDF okuma hatası: {e}"

def extract_text_from_docx(file_bytes):
    try:
        doc = Document(io.BytesIO(file_bytes))
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        return f"Docx okuma hatası: {e}"

def analyze_cv_with_ai(cv_text, api_key):
    client = openai.OpenAI(api_key=api_key)
    
    prompt = """
    Sen uzman bir İK asistanısın. Aşağıdaki CV metnini incele ve belirtilen kriterlere göre bir değerlendirme yap.
    
    KRİTERLER:
    1. Özel Eğitim / Gölge Öğretmenlik (LSA) tecrübesi var mı?
    2. Konuyla ilgili üniversite mezuniyeti (Psikoloji, Çocuk Gelişimi, Özel Eğitim vb.) var mı?
    3. Cinsiyet (Kullanıcı evde eğitim için özellikle KADIN aday tercih ediyor).
    4. Benzer görevleri daha önce yapmış mı?
    
    ÇIKTI FORMATI (JSON):
    {
        "ad_soyad": "Adayın Adı",
        "puan": (0-100 arası bir puan ver. Kadın olması, tecrübe ve ilgili bölüm mezuniyeti puanı artırmalı),
        "cinsiyet": "Kadın/Erkek/Belirsiz",
        "tecrube_yili": "Tahmini yıl",
        "ozet_yorum": "Aday hakkında 1 cümlelik Türkçe özet",
        "okul": "Mezun olduğu okul/bölüm"
    }
    
    Sadece JSON formatında yanıt ver.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o", # veya gpt-3.5-turbo
            messages=[
                {"role": "system", "content": "Sen JSON çıktısı veren bir yapay zeka asistanısın."},
                {"role": "user", "content": f"{prompt}\n\nCV METNİ:\n{cv_text[:4000]}"} # Token limiti için kısaltma
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"ad_soyad": "Hata", "puan": 0, "ozet_yorum": str(e)}

# --- Streamlit Arayüzü ---

st.set_page_config(page_title="LSA CV Analizcisi", layout="wide")

st.title("🧩 LSA / Gölge Öğretmen Aday Analizi")
st.markdown("Gmail 'LSA' etiketindeki CV'leri analiz eder ve en iyi adayları sıralar.")

with st.sidebar:
    st.header("Ayarlar")
    openai_key = st.text_input("OpenAI API Key", type="password")
    email_user = st.text_input("Gmail Adresi")
    email_pass = st.text_input("Gmail Uygulama Şifresi", type="password", help="Normal şifreniz değil, Google Hesabım > Güvenlik > Uygulama Şifreleri kısmından almalısınız.")
    label_name = st.text_input("Etiket Adı", value="LSA")
    limit = st.slider("İncelenecek Maksimum Mail", 5, 50, 10)
    start_btn = st.button("Analizi Başlat")

if start_btn:
    if not (openai_key and email_user and email_pass):
        st.error("Lütfen tüm bilgileri doldurun.")
    else:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            # Gmail Bağlantısı
            with MailBox('imap.gmail.com').login(email_user, email_pass) as mailbox:
                # Etikete göre filtrele (Klasör ismi genellikle etiket ismidir)
                # Not: Gmail'de etiketler klasör gibi davranır.
                mails = list(mailbox.fetch(AND(subject=all), limit=limit, reverse=True)) # Klasör seçimi aşağıda yapılacak
                
                # Etiket/Klasör seçimi için mailbox.folder.set kullanabiliriz ama 
                # imap_tools'da fetch sırasında klasör belirtmek daha sağlıklı:
                mailbox.folder.set(label_name)
                mails = list(mailbox.fetch(limit=limit, reverse=True))
                
                total_mails = len(mails)
                
                for i, msg in enumerate(mails):
                    status_text.text(f"İnceleniyor: {msg.subject} ({msg.date_str})")
                    
                    cv_text = ""
                    # Önce ekleri kontrol et
                    if msg.attachments:
                        for att in msg.attachments:
                            if att.filename.lower().endswith('.pdf'):
                                cv_text += extract_text_from_pdf(att.payload)
                            elif att.filename.lower().endswith('.docx'):
                                cv_text += extract_text_from_docx(att.payload)
                    
                    # Ek yoksa veya okunamazsa mail içeriğine bak
                    if len(cv_text) < 50:
                        cv_text = msg.text or msg.html
                    
                    # Eğer metin varsa AI'a gönder
                    if len(cv_text) > 50:
                        analysis = analyze_cv_with_ai(cv_text, openai_key)
                        analysis['email_konu'] = msg.subject
                        analysis['email_tarih'] = msg.date.strftime('%Y-%m-%d')
                        results.append(analysis)
                    
                    progress_bar.progress((i + 1) / total_mails)

            # Sonuçları Göster
            if results:
                df = pd.DataFrame(results)
                # Puanlamaya göre sırala
                df = df.sort_values(by='puan', ascending=False).head(10)
                
                st.success("Analiz Tamamlandı! İşte en iyi adaylar:")
                
                # Tabloyu düzenle
                st.dataframe(
                    df[['ad_soyad', 'puan', 'cinsiyet', 'tecrube_yili', 'okul', 'ozet_yorum', 'email_konu']],
                    use_container_width=True,
                    hide_index=True
                )
                
                # Detaylı görünüm
                st.subheader("Aday Detayları")
                for index, row in df.iterrows():
                    with st.expander(f"{row['puan']} Puan - {row['ad_soyad']}"):
                        st.write(f"**Özet:** {row['ozet_yorum']}")
                        st.write(f"**Okul:** {row['okul']}")
                        st.write(f"**Tecrübe:** {row['tecrube_yili']}")
                        st.write(f"**Mail Konusu:** {row['email_konu']}")

            else:
                st.warning("Hiçbir CV analiz edilemedi veya uygun mail bulunamadı.")

        except Exception as e:
            st.error(f"Bir hata oluştu: {e}")
            st.info("İpucu: Gmail ayarlarından IMAP'in açık olduğundan ve 'Uygulama Şifresi' kullandığınızdan emin olun.")
