from datetime import datetime
import streamlit as st
import requests
import time
from botocore.exceptions import ClientError

# Import shared utilities and config
import config

def home_page():
    """Home page with chat functionality."""
    st.title("Vergi Asistanı")
    
    # Import render_sidebar from sidebar module
    import sidebar
    uploaded_images, uploaded_audio = sidebar.render_sidebar()
    
    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []
     
    # Display previous messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
     
    user_input = st.chat_input("Your question...")
    
    if user_input:
        # --- Display user message ---
        with st.chat_message("user"):
            st.write(user_input)
            if uploaded_images:
                for img in uploaded_images:
                    st.image(img, caption=img.name, use_container_width=True)
            if uploaded_audio:
                st.audio(uploaded_audio, format="audio/mp3")
            st.session_state.messages.append({"role": "user", "content": user_input})

        with st.spinner("Generating response..."):
            start_time = time.time()
            # --- Prepare payload ---
            file_name_base = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            payload = {"user_input": user_input, "image_path": [], "audio_path": []}

            # Upload images to S3 and add S3 URIs
            if uploaded_images:
                # Check bucket access first
                has_access, access_msg = config.check_s3_access(config.S3_RECORDING_BUCKET)
                if not has_access:
                    st.error(f"❌ S3 Access Error: {access_msg}")
                    st.info("💡 **To fix this issue:**\n"
                           "1. Verify your AWS credentials are configured (check `~/.aws/credentials` or environment variables)\n"
                           "2. Ensure your IAM user/role has the following permissions:\n"
                           "   - `s3:PutObject` on `arn:aws:s3:::gelir-vergisi/images/*`\n"
                           "   - `s3:PutObject` on `arn:aws:s3:::gelir-vergisi/recordings/*`\n"
                           "   - `s3:ListBucket` on `arn:aws:s3:::gelir-vergisi`")
                else:
                    for img in uploaded_images:
                        image_name = f"{file_name_base}_{img.name}"
                        s3_key = f"{config.S3_IMAGE_PREFIX}{image_name}"
                        try:
                            # Reset file pointer to beginning
                            img.seek(0)
                            # Try upload with default settings first
                            try:
                                config.s3.upload_fileobj(img, config.S3_RECORDING_BUCKET, s3_key)
                            except ClientError as upload_error:
                                # If AccessDenied, try with server-side encryption
                                if upload_error.response.get("Error", {}).get("Code") == "AccessDenied":
                                    img.seek(0)
                                    config.s3.upload_fileobj(
                                        img, 
                                        config.S3_RECORDING_BUCKET, 
                                        s3_key,
                                        ExtraArgs={'ServerSideEncryption': 'AES256'}
                                    )
                                else:
                                    raise
                            payload["image_path"].append(f"s3://{config.S3_RECORDING_BUCKET}/{s3_key}")
                        except ClientError as e:
                            error_code = e.response.get("Error", {}).get("Code", "")
                            error_msg = e.response.get("Error", {}).get("Message", str(e))
                            error_details = e.response.get("Error", {})
                            
                            # Get account info for debugging
                            account_info = config.get_aws_account_info()
                            
                            if error_code == "AccessDenied":
                                st.error(f"❌ Access Denied uploading image {img.name}")
                                with st.expander("🔍 Error Details"):
                                    st.write(f"**Error Code:** {error_code}")
                                    st.write(f"**Message:** {error_msg}")
                                    st.write(f"**AWS Account:** {account_info.get('account_id', 'Unknown')}")
                                    st.write(f"**User ARN:** {account_info.get('user_arn', 'Unknown')}")
                                    st.write(f"**Bucket:** {config.S3_RECORDING_BUCKET}")
                                    st.write(f"**Key:** {s3_key}")
                                    st.write(f"**Region:** {config.S3_REGION}")
                                    st.json(error_details)
                                
                                st.warning("💡 **Possible causes:**\n"
                                          "1. Bucket policy is blocking access\n"
                                          "2. Bucket requires encryption headers\n"
                                          "3. Bucket ACL restrictions\n"
                                          "4. Wrong AWS account (check if bucket exists in this account)")
                            else:
                                st.error(f"❌ Error uploading image {img.name}: {error_code} - {error_msg}")
                                with st.expander("🔍 Error Details"):
                                    st.json(error_details)
                        except Exception as e:
                            st.error(f"❌ Unexpected error uploading image {img.name}: {e}")
                            st.exception(e)

            # Upload audio to S3 and add S3 URI
            if uploaded_audio:
                audio_name = f"{file_name_base}_{uploaded_audio.name}"
                s3_key = f"{config.S3_AUDIO_PREFIX}{audio_name}"
                try:
                    # Reset file pointer to beginning
                    uploaded_audio.seek(0)
                    # Try upload with default settings first
                    try:
                        config.s3.upload_fileobj(uploaded_audio, config.S3_RECORDING_BUCKET, s3_key)
                    except ClientError as upload_error:
                        # If AccessDenied, try with server-side encryption
                        if upload_error.response.get("Error", {}).get("Code") == "AccessDenied":
                            uploaded_audio.seek(0)
                            config.s3.upload_fileobj(
                                uploaded_audio, 
                                config.S3_RECORDING_BUCKET, 
                                s3_key,
                                ExtraArgs={'ServerSideEncryption': 'AES256'}
                            )
                        else:
                            raise
                    payload["audio_path"].append(f"s3://{config.S3_RECORDING_BUCKET}/{s3_key}")
                except ClientError as e:
                    error_code = e.response.get("Error", {}).get("Code", "")
                    error_msg = e.response.get("Error", {}).get("Message", str(e))
                    error_details = e.response.get("Error", {})
                    
                    # Get account info for debugging
                    account_info = config.get_aws_account_info()
                    
                    if error_code == "AccessDenied":
                        st.error(f"❌ Access Denied uploading audio {uploaded_audio.name}")
                        with st.expander("🔍 Error Details"):
                            st.write(f"**Error Code:** {error_code}")
                            st.write(f"**Message:** {error_msg}")
                            st.write(f"**AWS Account:** {account_info.get('account_id', 'Unknown')}")
                            st.write(f"**User ARN:** {account_info.get('user_arn', 'Unknown')}")
                            st.write(f"**Bucket:** {config.S3_RECORDING_BUCKET}")
                            st.write(f"**Key:** {s3_key}")
                            st.write(f"**Region:** {config.S3_REGION}")
                            st.json(error_details)
                        
                        st.warning("💡 **Possible causes:**\n"
                                  "1. Bucket policy is blocking access\n"
                                  "2. Bucket requires encryption headers\n"
                                  "3. Bucket ACL restrictions\n"
                                  "4. Wrong AWS account (check if bucket exists in this account)")
                    else:
                        st.error(f"❌ Error uploading audio {uploaded_audio.name}: {error_code} - {error_msg}")
                        with st.expander("🔍 Error Details"):
                            st.json(error_details)
                except Exception as e:
                    st.error(f"❌ Unexpected error uploading audio {uploaded_audio.name}: {e}")
                    st.exception(e)

            # --- Send to Lambda URL ---
            try:
                response = requests.post(config.API_URL, json=payload)
                response.raise_for_status()
                response_json = response.json()
                print()
                print(response_json)
                decoded = response_json.get("decoded_outputs", [])
                # frequency = response_json.get("kb_subjects_freq")
                assistant_output = decoded[0]["data"] if decoded else "No output returned."
            except requests.exceptions.RequestException as e:
                st.error(f"Error calling Lambda: {e}")
                assistant_output = None

            end_time = time.time()
            execution_time = end_time - start_time
            # --- Show assistant response ---
            if assistant_output:
                with st.chat_message("assistant"):
                    st.write(assistant_output)
                    st.session_state.messages.append({"role": "assistant", "content": assistant_output})
                    with st.expander("Details"):
                        st.write(f"Execution time: {execution_time:.4f} seconds")
                        # st.write(f"Frequency: {frequency}")
                    audio_bytes = config.tts_polly_safe(assistant_output)
                    st.audio(audio_bytes, format="audio/mp3")
                    # send_to_lambda(user_input, assistant_output, frequency, namespace="vergi")

    else:
        with st.chat_message("assistant"):
            st.write("Size nasıl yardımcı olabilirim?")
