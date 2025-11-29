import streamlit as st
import time
from datetime import timedelta
import xml.etree.ElementTree as ET
from xml.dom import minidom
import io
import json
import requests
from audio_recorder_streamlit import audio_recorder
import base64
from pathlib import Path
import os

# Streamlit Cloud Configuration
# Check if running on Streamlit Cloud
IS_STREAMLIT_CLOUD = os.getenv('STREAMLIT_SHARING_MODE') is not None

# Load API keys from Streamlit secrets if available
def load_api_keys():
    """Load API keys from Streamlit secrets or return empty dict"""
    try:
        if hasattr(st, 'secrets') and 'api_keys' in st.secrets:
            return {
                'anthropic': st.secrets['api_keys'].get('anthropic', ''),
                'elevenlabs': st.secrets['api_keys'].get('elevenlabs', ''),
                'openai': st.secrets['api_keys'].get('openai', '')
            }
    except Exception:
        pass
    
    return {
        'anthropic': '',
        'elevenlabs': '',
        'openai': ''
    }

# Initialize session state
if 'running' not in st.session_state:
    st.session_state.running = False
if 'start_time' not in st.session_state:
    st.session_state.start_time = None
if 'elapsed_time' not in st.session_state:
    st.session_state.elapsed_time = 0
if 'laps' not in st.session_state:
    st.session_state.laps = []
if 'current_lap_start' not in st.session_state:
    st.session_state.current_lap_start = 0
if 'transcription' not in st.session_state:
    st.session_state.transcription = ""
if 'script' not in st.session_state:
    st.session_state.script = ""
if 'generated_audio' not in st.session_state:
    st.session_state.generated_audio = {}
if 'music_request' not in st.session_state:
    st.session_state.music_request = {}
if 'sound_effects' not in st.session_state:
    st.session_state.sound_effects = {}
if 'api_keys' not in st.session_state:
    st.session_state.api_keys = load_api_keys()

def format_time(seconds):
    """Format seconds to HH:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"

def timecode_to_frames(seconds, fps=30):
    """Convert seconds to frame count"""
    return int(seconds * fps)

def transcribe_audio_openai_whisper(audio_bytes, api_key):
    """Transcribe audio using OpenAI Whisper API"""
    try:
        url = "https://api.openai.com/v1/audio/transcriptions"
        
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        
        files = {
            "file": ("audio.wav", audio_bytes, "audio/wav"),
            "model": (None, "whisper-1")
        }
        
        response = requests.post(url, headers=headers, files=files, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            return result.get('text', '')
        else:
            st.error(f"Whisper API Error: {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        st.error("Transcription timeout. Please try with a shorter recording.")
        return None
    except Exception as e:
        st.error(f"Transcription error: {str(e)}")
        return None

def generate_script_with_claude(transcription, api_key, additional_instructions=""):
    """Generate audio tour script using Claude API"""
    try:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        base_prompt = f"""Based on the following research notes and brainstorming session for an audio tour, 
create a comprehensive, engaging audio tour script. The script should be professional, informative, 
and designed to be narrated. Include natural pauses, emotional cues, and make it suitable for 
text-to-speech generation.

Research Notes:
{transcription}

{additional_instructions}

Please structure the script with:
1. An engaging introduction
2. Clear sections for different tour stops/points
3. Interesting facts and storytelling elements
4. Natural transitions between sections
5. A memorable conclusion

Format each section clearly so it can be easily divided for production.
Use natural, conversational language that sounds good when spoken aloud."""

        data = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4000,
            "messages": [
                {"role": "user", "content": base_prompt}
            ]
        }
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=data,
            timeout=90
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['content'][0]['text']
        else:
            st.error(f"Claude API Error: {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        st.error("Request timed out. Please try again.")
        return None
    except Exception as e:
        st.error(f"Script generation error: {str(e)}")
        return None

def generate_audio_elevenlabs(text, voice_id, api_key, voice_settings=None):
    """Generate audio using ElevenLabs API"""
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key
        }
        
        if voice_settings is None:
            voice_settings = {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.5,
                "use_speaker_boost": True
            }
        
        data = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": voice_settings
        }
        
        response = requests.post(url, json=data, headers=headers, timeout=120)
        
        if response.status_code == 200:
            return response.content
        else:
            error_message = f"ElevenLabs API Error: {response.status_code}"
            try:
                error_data = response.json()
                error_message += f" - {error_data.get('detail', {}).get('message', '')}"
            except:
                pass
            st.error(error_message)
            return None
            
    except requests.exceptions.Timeout:
        st.error("Audio generation timeout. Text may be too long. Try splitting into smaller sections.")
        return None
    except Exception as e:
        st.error(f"Audio generation error: {str(e)}")
        return None

def generate_sound_effects_elevenlabs(description, api_key, duration_seconds=5):
    """Generate sound effects using ElevenLabs Sound Effects API"""
    try:
        url = "https://api.elevenlabs.io/v1/sound-generation"
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key
        }
        
        data = {
            "text": description,
            "duration_seconds": duration_seconds,
        }
        
        response = requests.post(url, json=data, headers=headers, timeout=60)
        
        if response.status_code == 200:
            return response.content
        else:
            st.error(f"Sound Effects API Error: {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        st.error("Sound effect generation timeout. Please try again.")
        return None
    except Exception as e:
        st.error(f"Sound effects generation error: {str(e)}")
        return None

def create_suno_music_request(prompt, duration=120, style="instrumental", mood="ambient"):
    """Create a music generation request for Suno AI"""
    music_request = {
        "prompt": prompt,
        "duration": duration,
        "style": style,
        "mood": mood,
        "created_at": time.time(),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    return music_request

def generate_resolve_xml(laps, fps=30, project_name="Audio Tour Timeline"):
    """Generate DaVinci Resolve compatible XML with markers"""
    xmeml = ET.Element('xmeml', version='4')
    
    sequence = ET.SubElement(xmeml, 'sequence')
    ET.SubElement(sequence, 'name').text = project_name
    ET.SubElement(sequence, 'duration').text = str(timecode_to_frames(laps[-1]['end_time'], fps) if laps else 0)
    
    rate = ET.SubElement(sequence, 'rate')
    ET.SubElement(rate, 'timebase').text = str(fps)
    ET.SubElement(rate, 'ntsc').text = 'FALSE'
    
    timecode = ET.SubElement(sequence, 'timecode')
    ET.SubElement(timecode, 'rate')
    rate_tc = timecode.find('rate')
    ET.SubElement(rate_tc, 'timebase').text = str(fps)
    ET.SubElement(rate_tc, 'ntsc').text = 'FALSE'
    ET.SubElement(timecode, 'string').text = '00:00:00:00'
    ET.SubElement(timecode, 'frame').text = '0'
    
    media = ET.SubElement(sequence, 'media')
    video = ET.SubElement(media, 'video')
    track = ET.SubElement(video, 'track')
    
    for i, lap in enumerate(laps):
        clipitem = ET.SubElement(track, 'clipitem', id=f"clipitem-{i+1}")
        ET.SubElement(clipitem, 'name').text = lap['title']
        ET.SubElement(clipitem, 'duration').text = str(timecode_to_frames(lap['duration'], fps))
        
        clip_rate = ET.SubElement(clipitem, 'rate')
        ET.SubElement(clip_rate, 'timebase').text = str(fps)
        ET.SubElement(clip_rate, 'ntsc').text = 'FALSE'
        
        ET.SubElement(clipitem, 'in').text = '0'
        ET.SubElement(clipitem, 'out').text = str(timecode_to_frames(lap['duration'], fps))
        ET.SubElement(clipitem, 'start').text = str(timecode_to_frames(lap['start_time'], fps))
        ET.SubElement(clipitem, 'end').text = str(timecode_to_frames(lap['end_time'], fps))
        
        marker = ET.SubElement(clipitem, 'marker')
        ET.SubElement(marker, 'name').text = lap['title']
        ET.SubElement(marker, 'comment').text = f"Duration: {format_time(lap['duration'])}"
        ET.SubElement(marker, 'in').text = str(timecode_to_frames(lap['start_time'], fps))
        ET.SubElement(marker, 'out').text = str(timecode_to_frames(lap['end_time'], fps))
    
    xml_string = ET.tostring(xmeml, encoding='unicode')
    dom = minidom.parseString(xml_string)
    return dom.toprettyxml(indent='  ')

# Page config
st.set_page_config(
    page_title="Audio Tour Production Studio",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better cloud display
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
    }
    /* Better spacing on mobile */
    @media (max-width: 768px) {
        .stColumn {
            padding: 0.5rem;
        }
    }
</style>
""", unsafe_allow_html=True)

# Sidebar for API Configuration
with st.sidebar:
    st.header("⚙️ API Configuration")
    
    # Show info about cloud deployment
    if IS_STREAMLIT_CLOUD:
        st.info("🌥️ Running on Streamlit Cloud\nAPI keys loaded from Secrets")
    
    # Only show API key inputs if secrets aren't configured
    if not st.session_state.api_keys.get('anthropic'):
        st.session_state.api_keys['anthropic'] = st.text_input(
            "Anthropic API Key",
            value=st.session_state.api_keys.get('anthropic', ''),
            type="password",
            help="Your Claude API key for script generation. Add to Streamlit Secrets for cloud deployment."
        )
    else:
        st.success("✅ Anthropic API key loaded from secrets")
    
    if not st.session_state.api_keys.get('elevenlabs'):
        st.session_state.api_keys['elevenlabs'] = st.text_input(
            "ElevenLabs API Key",
            value=st.session_state.api_keys.get('elevenlabs', ''),
            type="password",
            help="Your ElevenLabs API key for audio & sound effects"
        )
    else:
        st.success("✅ ElevenLabs API key loaded from secrets")
    
    if not st.session_state.api_keys.get('openai'):
        st.session_state.api_keys['openai'] = st.text_input(
            "OpenAI API Key (Optional)",
            value=st.session_state.api_keys.get('openai', ''),
            type="password",
            help="For Whisper transcription service"
        )
    elif st.session_state.api_keys.get('openai'):
        st.success("✅ OpenAI API key loaded from secrets")
    
    st.divider()
    
    st.header("🎤 Voice Settings")
    
    voice_options = {
        "Rachel (Clear, Professional)": "21m00Tcm4TlvDq8ikWAM",
        "Domi (Confident, Versatile)": "AZnzlk1XvdvUeBnXmlld",
        "Bella (Warm, Engaging)": "EXAVITQu4vr4xnSDxMaL",
        "Antoni (Friendly Male)": "ErXwobaYiN019PkySvjV",
        "Elli (Energetic)": "MF3mGyEYCl7XYWbV9V6O",
        "Josh (Deep, Authoritative)": "TxGEqnHWrfWFTfGW9XjX",
    }
    
    selected_voice = st.selectbox(
        "Select Voice",
        options=list(voice_options.keys()),
        help="Choose the voice for narration"
    )
    voice_id = voice_options[selected_voice]
    
    st.write("**Voice Parameters:**")
    stability = st.slider("Stability", 0.0, 1.0, 0.5, 0.05, 
                          help="Higher = more consistent, Lower = more expressive")
    similarity = st.slider("Similarity", 0.0, 1.0, 0.75, 0.05,
                          help="How closely to match the original voice")
    style = st.slider("Style", 0.0, 1.0, 0.5, 0.05,
                      help="Adds emotional range and expressiveness")
    
    voice_settings = {
        "stability": stability,
        "similarity_boost": similarity,
        "style": style,
        "use_speaker_boost": True
    }
    
    st.divider()
    
    st.header("📊 Project Stats")
    st.metric("Total Sections", len(st.session_state.laps))
    st.metric("Audio Files", len(st.session_state.generated_audio))
    st.metric("Sound Effects", len(st.session_state.sound_effects))
    
    # Cloud deployment info
    if IS_STREAMLIT_CLOUD:
        st.divider()
        st.caption("☁️ Streamlit Cloud Deployment")
        st.caption("Session data is temporary")

# Main title
st.title("🎙️ Audio Tour Production Studio")
st.markdown("""
Complete audio tour production workflow: Record → Transcribe → Generate Script → 
Produce Audio → Create Music & Sound Effects → Export Timeline
""")

# Progress indicator
progress_stages = {
    "Research": bool(st.session_state.transcription),
    "Script": bool(st.session_state.script),
    "Timeline": bool(st.session_state.laps),
    "Audio": bool(st.session_state.generated_audio)
}

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.write("🎤" + (" ✅" if progress_stages["Research"] else ""), "Research")
with col2:
    st.write("📝" + (" ✅" if progress_stages["Script"] else ""), "Script")
with col3:
    st.write("⏱️" + (" ✅" if progress_stages["Timeline"] else ""), "Timeline")
with col4:
    st.write("🎵" + (" ✅" if progress_stages["Audio"] else ""), "Audio")

st.divider()

# Create tabs for different workflow stages
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🎤 Record & Research",
    "📝 Script Generation",
    "⏱️ Timeline & Sections",
    "🎵 Audio Production",
    "📤 Export & Download"
])

# TAB 1: Recording and Research
with tab1:
    st.header("Step 1: Record Your Research & Brainstorming")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("🎙️ Voice Recording")
        st.info("Record your thoughts, research notes, and ideas for the audio tour")
        
        try:
            audio_bytes = audio_recorder(
                text="Click to record",
                recording_color="#e74c3c",
                neutral_color="#3498db",
                icon_name="microphone",
                icon_size="3x",
            )
            
            if audio_bytes:
                st.audio(audio_bytes, format="audio/wav")
                
                if st.button("🔄 Transcribe Recording", type="primary", disabled=not st.session_state.api_keys['openai']):
                    with st.spinner("Transcribing audio..."):
                        transcription = transcribe_audio_openai_whisper(
                            audio_bytes,
                            st.session_state.api_keys['openai']
                        )
                        
                        if transcription:
                            st.session_state.transcription = transcription
                            st.success("✅ Transcription complete!")
                            st.rerun()
                
                if not st.session_state.api_keys['openai']:
                    st.warning("⚠️ Add your OpenAI API key in the sidebar to enable transcription")
        except Exception as e:
            st.warning("⚠️ Audio recorder not available. Please use manual text input below.")
    
    with col2:
        st.subheader("📝 Manual Research Input")
        manual_input = st.text_area(
            "Or type your research notes directly:",
            value=st.session_state.transcription if st.session_state.transcription else "",
            height=300,
            placeholder="Enter your research, facts, ideas, and tour content here..."
        )
        
        if st.button("💾 Save Research Notes"):
            st.session_state.transcription = manual_input
            st.success("✅ Research notes saved!")
            st.rerun()
    
    if st.session_state.transcription:
        st.divider()
        st.subheader("📄 Current Research Notes")
        with st.expander("View Research Content", expanded=False):
            st.text_area("Research & Brainstorming", st.session_state.transcription, height=200, disabled=True)
            
            word_count = len(st.session_state.transcription.split())
            st.caption(f"📊 Word count: {word_count}")

# TAB 2: Script Generation
with tab2:
    st.header("Step 2: Generate Audio Tour Script")
    
    if not st.session_state.transcription:
        st.warning("⚠️ Please complete Step 1: Record or enter your research notes first")
    else:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.info("📝 Ready to generate your professional audio tour script using AI")
            
            additional_instructions = st.text_area(
                "Additional Instructions (Optional)",
                placeholder="E.g., Make it more casual, focus on families with children, include humor, etc.",
                height=100
            )
            
            if st.button("🤖 Generate Script with Claude", type="primary", disabled=not st.session_state.api_keys['anthropic']):
                with st.spinner("Generating script... This may take up to 90 seconds."):
                    script = generate_script_with_claude(
                        st.session_state.transcription,
                        st.session_state.api_keys['anthropic'],
                        additional_instructions
                    )
                    
                    if script:
                        st.session_state.script = script
                        st.success("✅ Script generated successfully!")
                        st.rerun()
        
        with col2:
            if not st.session_state.api_keys['anthropic']:
                st.error("❌ Please add your Anthropic API key in the sidebar or Streamlit Secrets")
    
    if st.session_state.script:
        st.divider()
        st.subheader("📖 Generated Script")
        
        edited_script = st.text_area(
            "Edit script if needed:",
            value=st.session_state.script,
            height=400,
            help="You can edit the generated script before proceeding to audio production"
        )
        
        if edited_script != st.session_state.script:
            if st.button("💾 Save Script Changes"):
                st.session_state.script = edited_script
                st.success("✅ Script updated!")
        
        # Word count for script
        script_word_count = len(st.session_state.script.split())
        estimated_time = script_word_count / 150  # Average speaking rate
        st.caption(f"📊 Script: {script_word_count} words | Estimated time: {estimated_time:.1f} minutes")

# TAB 3: Timeline and Sections
with tab3:
    st.header("Step 3: Create Timeline & Section Markers")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("⏱️ Timer Control")
        
        if st.session_state.running and st.session_state.start_time:
            current_elapsed = st.session_state.elapsed_time + (time.time() - st.session_state.start_time)
        else:
            current_elapsed = st.session_state.elapsed_time
        
        timer_display = st.empty()
        timer_display.markdown(f"## `{format_time(current_elapsed)}`")
        
        button_col1, button_col2, button_col3 = st.columns(3)
        
        with button_col1:
            if not st.session_state.running:
                if st.button("▶️ Start", use_container_width=True, type="primary"):
                    st.session_state.running = True
                    st.session_state.start_time = time.time()
                    st.rerun()
            else:
                if st.button("⏸️ Pause", use_container_width=True):
                    st.session_state.running = False
                    st.session_state.elapsed_time += time.time() - st.session_state.start_time
                    st.session_state.start_time = None
                    st.rerun()
        
        with button_col2:
            if st.button("⏹️ Stop Lap", use_container_width=True, disabled=not st.session_state.running and st.session_state.elapsed_time == 0):
                lap_end_time = current_elapsed
                
                st.session_state.laps.append({
                    'start_time': st.session_state.current_lap_start,
                    'end_time': lap_end_time,
                    'duration': lap_end_time - st.session_state.current_lap_start,
                    'title': f"Section {len(st.session_state.laps) + 1}",
                    'script_text': ""
                })
                
                st.session_state.current_lap_start = lap_end_time
                st.rerun()
        
        with button_col3:
            if st.button("🔄 Reset All", use_container_width=True):
                st.session_state.running = False
                st.session_state.start_time = None
                st.session_state.elapsed_time = 0
                st.session_state.laps = []
                st.session_state.current_lap_start = 0
                st.rerun()
    
    with col2:
        st.subheader("📝 Section Details")
        
        if st.session_state.laps:
            st.info(f"**Total Sections:** {len(st.session_state.laps)}")
            
            for i, lap in enumerate(st.session_state.laps):
                with st.expander(f"Section {i+1}: {lap['title']}", expanded=False):
                    new_title = st.text_input(
                        "Section Title",
                        value=lap['title'],
                        key=f"title_{i}"
                    )
                    st.session_state.laps[i]['title'] = new_title
                    
                    script_text = st.text_area(
                        "Script for this section",
                        value=lap.get('script_text', ''),
                        key=f"script_{i}",
                        help="Add the portion of the script for this section",
                        height=150
                    )
                    st.session_state.laps[i]['script_text'] = script_text
                    
                    st.write(f"**Start:** `{format_time(lap['start_time'])}`")
                    st.write(f"**End:** `{format_time(lap['end_time'])}`")
                    st.write(f"**Duration:** `{format_time(lap['duration'])}`")
                    
                    if script_text:
                        words = len(script_text.split())
                        st.caption(f"📝 {words} words")
                    
                    if st.button(f"🗑️ Delete Section {i+1}", key=f"delete_{i}"):
                        st.session_state.laps.pop(i)
                        st.rerun()
        else:
            st.info("No sections recorded yet. Start the timer and create your first section!")

# TAB 4: Audio Production
with tab4:
    st.header("Step 4: Generate Audio, Music & Sound Effects")
    
    if not st.session_state.laps:
        st.warning("⚠️ Please create timeline sections in Step 3 first")
    elif not st.session_state.api_keys['elevenlabs']:
        st.error("❌ Please add your ElevenLabs API key in the sidebar or Streamlit Secrets")
    else:
        # Audio generation for sections
        st.subheader("🎙️ Narration Generation")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if st.button("🎵 Generate All Section Audio", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                sections_with_script = [lap for lap in st.session_state.laps if lap.get('script_text')]
                
                if not sections_with_script:
                    st.warning("⚠️ No sections have script text assigned. Add script text in Step 3.")
                else:
                    for i, lap in enumerate(st.session_state.laps):
                        if lap.get('script_text'):
                            status_text.text(f"Generating audio for: {lap['title']}")
                            
                            audio_data = generate_audio_elevenlabs(
                                lap['script_text'],
                                voice_id,
                                st.session_state.api_keys['elevenlabs'],
                                voice_settings
                            )
                            
                            if audio_data:
                                st.session_state.generated_audio[f"section_{i}"] = {
                                    'audio': audio_data,
                                    'title': lap['title']
                                }
                        
                        progress_bar.progress((i + 1) / len(st.session_state.laps))
                    
                    status_text.text("✅ All audio generated!")
                    st.success(f"Generated audio for {len(st.session_state.generated_audio)} sections")
                    st.rerun()
        
        with col2:
            if st.session_state.generated_audio:
                st.metric("Generated Files", len(st.session_state.generated_audio))
        
        # Display generated audio
        if st.session_state.generated_audio:
            st.divider()
            st.subheader("🎧 Generated Audio Sections")
            
            for key, data in st.session_state.generated_audio.items():
                with st.expander(f"🔊 {data['title']}", expanded=False):
                    st.audio(data['audio'], format='audio/mpeg')
        
        # Sound Effects
        st.divider()
        st.subheader("🔊 Sound Effects Generation")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            sfx_description = st.text_input(
                "Describe sound effect",
                placeholder="e.g., footsteps on marble floor, door creaking, ambient museum sounds"
            )
            
            sfx_duration = st.slider("Duration (seconds)", 1, 15, 5)
        
        with col2:
            st.write("")
            st.write("")
            if st.button("🎵 Generate Sound Effect"):
                if sfx_description:
                    with st.spinner("Generating sound effect..."):
                        sfx_audio = generate_sound_effects_elevenlabs(
                            sfx_description,
                            st.session_state.api_keys['elevenlabs'],
                            sfx_duration
                        )
                        
                        if sfx_audio:
                            sfx_key = f"sfx_{len(st.session_state.sound_effects)}"
                            st.session_state.sound_effects[sfx_key] = {
                                'audio': sfx_audio,
                                'description': sfx_description
                            }
                            st.success("✅ Sound effect generated!")
                            st.rerun()
                else:
                    st.warning("⚠️ Please enter a sound effect description")
        
        if st.session_state.sound_effects:
            st.write("**Generated Sound Effects:**")
            for key, data in st.session_state.sound_effects.items():
                with st.expander(f"🔊 {data['description']}", expanded=False):
                    st.audio(data['audio'], format='audio/mpeg')
        
        # Music Generation Request
        st.divider()
        st.subheader("🎼 Background Music Request (Suno AI)")
        
        st.info("📝 Note: Suno AI doesn't have a public API yet. This creates a structured request for when it becomes available.")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            music_prompt = st.text_area(
                "Music Description",
                placeholder="e.g., Ambient instrumental music with a mysterious atmosphere, slow tempo, orchestral elements",
                height=100
            )
            
            music_duration = st.slider("Duration (seconds)", 30, 300, 120)
            
            music_style = st.selectbox("Style", ["instrumental", "ambient", "classical", "electronic", "cinematic"])
            music_mood = st.selectbox("Mood", ["ambient", "uplifting", "mysterious", "calm", "energetic", "dramatic"])
        
        with col2:
            st.write("")
            st.write("")
            if st.button("📝 Create Music Request"):
                if music_prompt:
                    request = create_suno_music_request(music_prompt, music_duration, music_style, music_mood)
                    request_key = f"music_{len(st.session_state.music_request)}"
                    st.session_state.music_request[request_key] = request
                    st.success("✅ Music request created!")
                    st.rerun()
                else:
                    st.warning("⚠️ Please enter a music description")
        
        if st.session_state.music_request:
            st.write("**Music Generation Requests:**")
            for key, request in st.session_state.music_request.items():
                with st.expander(f"🎼 {request['prompt'][:50]}...", expanded=False):
                    st.json(request)

# TAB 5: Export and Download
with tab5:
    st.header("Step 5: Export & Download")
    
    # XML Timeline Export
    st.subheader("📄 DaVinci Resolve Timeline XML")
    
    if st.session_state.laps:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            fps = st.selectbox(
                "Frame Rate (FPS)",
                options=[24, 25, 30, 60],
                index=2
            )
            
            project_name = st.text_input("Project Name", value="Audio Tour Timeline")
        
        with col2:
            st.write("")
            st.write("")
            xml_content = generate_resolve_xml(st.session_state.laps, fps, project_name)
            
            st.download_button(
                label="⬇️ Download Timeline XML",
                data=xml_content,
                file_name=f"{project_name.replace(' ', '_')}.xml",
                mime="application/xml",
                use_container_width=True,
                type="primary"
            )
    else:
        st.info("Create timeline sections to enable XML export")
    
    # Audio Files Export
    st.divider()
    st.subheader("🎧 Download Generated Audio")
    
    if st.session_state.generated_audio:
        for key, data in st.session_state.generated_audio.items():
            st.download_button(
                label=f"⬇️ {data['title']}",
                data=data['audio'],
                file_name=f"{data['title'].replace(' ', '_')}.mp3",
                mime="audio/mpeg",
                key=f"download_{key}"
            )
    else:
        st.info("Generate audio in Step 4 to enable downloads")
    
    # Sound Effects Export
    st.divider()
    st.subheader("🔊 Download Sound Effects")
    
    if st.session_state.sound_effects:
        for key, data in st.session_state.sound_effects.items():
            st.download_button(
                label=f"⬇️ {data['description']}",
                data=data['audio'],
                file_name=f"sfx_{data['description'][:30].replace(' ', '_')}.mp3",
                mime="audio/mpeg",
                key=f"download_{key}"
            )
    else:
        st.info("Generate sound effects in Step 4 to enable downloads")
    
    # Music Requests Export
    st.divider()
    st.subheader("🎼 Export Music Requests")
    
    if st.session_state.music_request:
        music_json = json.dumps(st.session_state.music_request, indent=2)
        
        st.download_button(
            label="⬇️ Download Music Requests (JSON)",
            data=music_json,
            file_name="suno_music_requests.json",
            mime="application/json"
        )
        
        st.info("💡 Use this JSON file to submit requests to Suno AI when their API becomes available")
    else:
        st.info("Create music requests in Step 4 to enable export")
    
    # Project Summary
    st.divider()
    st.subheader("📊 Project Summary")
    
    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
    
    with summary_col1:
        st.metric("Sections", len(st.session_state.laps))
    
    with summary_col2:
        st.metric("Audio Files", len(st.session_state.generated_audio))
    
    with summary_col3:
        st.metric("Sound Effects", len(st.session_state.sound_effects))
    
    with summary_col4:
        st.metric("Music Requests", len(st.session_state.music_request))
    
    # Cloud storage warning
    if IS_STREAMLIT_CLOUD:
        st.divider()
        st.warning("☁️ **Cloud Deployment Note:** All generated files are stored in session memory only. Download all files before closing the browser or the session will be lost.")

# Auto-refresh for running timer (with reduced frequency for cloud)
if st.session_state.running:
    time.sleep(0.1 if not IS_STREAMLIT_CLOUD else 0.5)
    st.rerun()
