import streamlit as st
import pandas as pd
import openai
from imap_tools import MailBox
import PyPDF2
from docx import Document
import io
import json

# --- Yardımcı Fonksiyonlar ---

def extract_text_from_pdf(file_bytes):
    """PDF dosyasından metin ayıklar."""
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        return ""

def extract_text_from_docx(file_bytes):
    """Word dosyasından metin ayıklar."""
    try:
        doc = Document(io.BytesIO(file_bytes))
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        return ""

def analyze_cv_with_ai(cv_text, api_key):
    """CV metnini OpenAI API'ye gönderir ve puanlar."""
    client = openai.OpenAI(api_key=api_key)
    
    prompt = """
    Sen uzman bir İK asistanısın. Aşağıdaki CV metnini LSA (Learning Support Assistant) pozisyonu için incele.
    
    DEĞERLENDİRME KRİTERLERİ:
    1. **Özel Eğitim / LSA Tecrübesi:** Var mı? Kaç yıl? (En önemli kriter)
    2. **Eğitim:** İlgili bölümlerden mi mezun? (Psikoloji, Çocuk Gelişimi, PDR, Özel Eğitim vb.)
    3. **Cinsiyet:** İşveren evde eğitim için KADIN aday tercih ediyor.
    4. **Benzer Görevler:** Daha önce gölge öğretmenlik veya evde eğitim desteği vermiş mi?
    
    ÇIKTI FORMATI (Sadece JSON):
    {
        "ad_soyad": "Adayın Adı (Bulamazsan 'Belirsiz')",
        "puan": (0-100 arası bir puan ver. Kadın + İlgili Bölüm + Tecrübe = 90+ puan),
        "cinsiyet": "Kadın/Erkek/Belirsiz",
        "tecrube_yili": "Tahmini Yıl",
        "ozet_yorum": "Aday hakkında Türkçe, kısa ve net bir değerlendirme cümlesi.",
        "okul": "Mezun olduğu okul/bölüm"
    }
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Eğer 4o pahalı gelirse "gpt-3.5-turbo" yapabilirsin
            messages=[
                {"role": "system", "content": "Sen JSON çıktısı veren bir asistansın."},
                {"role": "user", "content": f"{prompt}\n\nİNCELENECEK CV METNİ:\n{cv_text[:4000]}"}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"ad_soyad": "Hata", "puan": 0, "ozet_yorum": f"AI Hatası: {str(e)}"}

# --- Streamlit Arayüzü ---

st.set_page_config(page_title="LSA CV Tarayıcı", page_icon="🧩", layout="wide")

st.title("🧩 LSA / Gölge Öğretmen Aday Analizi")
st.markdown("""
Bu uygulama Gmail hesabınızdaki **belirlenen etiketteki** e-postaları tarar, 
eklerdeki CV'leri (PDF/DOCX) okur ve yapay zeka ile puanlar.
""")

with st.sidebar:
    st.header("⚙️ Ayarlar")
    
    # Kullanıcıdan bilgiler alınıyor
    openai_key = st.text_input("OpenAI API Key", type="password", help="sk-... ile başlayan anahtar")
    email_user = st.text_input("Gmail Adresi")
    email_pass = st.text_input("Gmail Uygulama Şifresi", type="password", help="Normal şifreniz değil, 16 haneli Uygulama Şifresi")
    label_name = st.text_input("Gmail Etiket Adı", value="LSA", help="Gmail'deki etiket ismiyle birebir aynı olmalı.")
    limit = st.slider("İncelenecek Mail Sayısı", 5, 50, 10)
    
    start_btn = st.button("Analizi Başlat", type="primary")

if start_btn:
    if not (openai_key and email_user and email_pass and label_name):
        st.warning("Lütfen sol menüdeki tüm bilgileri eksiksiz doldurun.")
    else:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # IMAP Sunucusuna Bağlan
            with MailBox('imap.gmail.com').login(email_user, email_pass) as mailbox:
                
                # Klasör/Etiket Seçimi
                try:
                    mailbox.folder.set(label_name)
                except Exception as e:
                    st.error(f"Etiket hatası: '{label_name}' etiketi Gmail hesabınızda bulunamadı veya 'IMAP'te göster' seçeneği kapalı.")
                    st.stop()

                # Mailleri Çek
                status_text.text("Mailler listeleniyor...")
                mails = list(mailbox.fetch(limit=limit, reverse=True))
                total_mails = len(mails)

                if total_mails == 0:
                    st.info(f"'{label_name}' etiketinde hiç mail bulunamadı.")
                
                for i, msg in enumerate(mails):
                    status_text.text(f"İnceleniyor ({i+1}/{total_mails}): {msg.subject}")
                    
                    cv_text = ""
                    has_attachment = False
                    
                    # 1. Ekleri Kontrol Et (PDF/DOCX)
                    if msg.attachments:
                        for att in msg.attachments:
                            if att.filename.lower().endswith('.pdf'):
                                cv_text += extract_text_from_pdf(att.payload)
                                has_attachment = True
                            elif att.filename.lower().endswith('.docx'):
                                cv_text += extract_text_from_docx(att.payload)
                                has_attachment = True
                    
                    # 2. Ek yoksa veya okunamadıysa mail gövdesini al
                    if len(cv_text) < 100: 
                        soup_text = msg.text or msg.html
                        if soup_text:
                            cv_text += "\n" + soup_text
                    
                    # 3. Yeterli metin varsa AI'a gönder
                    if len(cv_text) > 50:
                        analysis = analyze_cv_with_ai(cv_text, openai_key)
                        analysis['email_konu'] = msg.subject
                        analysis['email_tarih'] = msg.date.strftime('%Y-%m-%d')
                        results.append(analysis)
                    
                    # İlerleme çubuğunu güncelle
                    progress_bar.progress((i + 1) / total_mails)

            # Sonuç Ekranı
            status_text.text("Analiz tamamlandı.")
            progress_bar.empty()

            if results:
                df = pd.DataFrame(results)
                # Puana göre sırala (En yüksek puan en üstte)
                df = df.sort_values(by='puan', ascending=False)
                
                # İkonlu metrikler
                top_candidate = df.iloc[0]
                st.success(f"En İyi Aday: {top_candidate['ad_soyad']} ({top_candidate['puan']} Puan)")
                
                # Tablo Görünümü
                st.dataframe(
                    df[['puan', 'ad_soyad', 'cinsiyet', 'tecrube_yili', 'okul', 'ozet_yorum', 'email_konu']],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "puan": st.column_config.ProgressColumn("Uygunluk", format="%d", min_value=0, max_value=100),
                    }
                )
            else:
                st.warning("Mailler tarandı ancak analiz edilecek uygun içerik/CV bulunamadı.")

        except Exception as e:
            st.error(f"Bağlantı Hatası: {e}")
            st.info("Lütfen Gmail 'Uygulama Şifresi'nizi ve internet bağlantınızı kontrol edin.")
