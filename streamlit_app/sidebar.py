import streamlit as st
import config

def render_sidebar():
    """Render the sidebar content that appears on all pages."""
    with st.sidebar:
        st.sidebar.title("Ayarlar")

        # AWS Diagnostics
        with st.expander("🔧 AWS Diagnostics", expanded=False):
            account_info = config.get_aws_account_info()
            if "error" not in account_info:
                st.success("✅ AWS Credentials: Valid")
                st.write(f"**Account ID:** {account_info.get('account_id', 'Unknown')}")
                st.write(f"**User ARN:** {account_info.get('user_arn', 'Unknown')}")
            else:
                st.error(f"❌ AWS Credentials Error: {account_info.get('error')}")
            
            # Check bucket access
            has_access, access_msg = config.check_s3_access(config.S3_RECORDING_BUCKET)
            if has_access:
                st.success(f"✅ Bucket Access: {config.S3_RECORDING_BUCKET}")
            else:
                st.error(f"❌ Bucket Access: {access_msg}")

        st.sidebar.title("Dosya Yükle")
     
        # Image/document upload (preview only)
        uploaded_images = st.file_uploader(
            "Bir belge seç",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="image_uploader",
        )
     
        if uploaded_images:
            st.sidebar.write("Önizleme:")
            for img in uploaded_images:
                st.image(img, caption=img.name, use_container_width=True)
     
        # # Audio file (preview only)
        # uploaded_audio = st.file_uploader(
        #     "Ses Dosyası Yükle",
        #     type=["mp3", "wav", "m4a", "ogg"],
        #     accept_multiple_files=False,
        #     key="audio_uploader",
        # )
     
        # if uploaded_audio:
        #     st.audio(uploaded_audio, format="audio/mp3")
     
        # # --- 🎤 Audio Recorder ---
        # st.sidebar.title("Ses Kaydet")
        # recorded_audio = st.audio_input("Sesli mesaj kaydet")
     
        # if recorded_audio:
        #     st.sidebar.audio(recorded_audio, format="audio/mp3")
        #     # Treat recorded audio as if uploaded
        #     uploaded_audio = recorded_audio
     
        st.sidebar.title("Örnek Sorular")
        st.write(
            "Gelirin unsurları nelerdir?",
        )
        st.write(
            "Merhaba, Ocak 2024 döneminde bazı faturalarımızda KDV oranını yanlışlıkla yüzde 20 yerine yüzde 10 uyguladığımızı fark ettik. Bu nedenle beyannamenin düzeltilmesini talep ediyoruz.",
        )
        st.write(
            "İç denetimde, 2024/Ocak dönemine ait bazı hizmet faturalarında KDV oranının hatalı uygulandığı tespit edilmiştir. Sorunun çözümü için referans alınması gereken mevzuatlar nelerdir?",
        )
    
    return uploaded_images
