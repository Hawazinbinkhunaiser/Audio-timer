import streamlit as st
import time
from datetime import timedelta
import xml.etree.ElementTree as ET
from xml.dom import minidom
import io
import os
from pathlib import Path
import json
import requests
from audio_recorder_streamlit import audio_recorder
import anthropic
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs
import tempfile

# Page config
st.set_page_config(
    page_title="Audio Tour Production Studio",
    page_icon="🎙️",
    layout="wide"
)

# Initialize session state
def init_session_state():
    defaults = {
        'running': False,
        'start_time': None,
        'elapsed_time': 0,
        'laps': [],
        'current_lap_start': 0,
        'workflow_stage': 'recording',  # recording, transcription, script_generation, audio_production, final
        'recordings': [],
        'transcriptions': [],
        'research_notes': '',
        'final_script': '',
        'generated_audios': [],
        'music_requests': [],
        'sfx_requests': [],
        'project_name': 'My Audio Tour'
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Helper Functions
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

def transcribe_audio(audio_bytes, api_key):
    """Transcribe audio using AssemblyAI"""
    try:
        headers = {
            "authorization": api_key,
            "content-type": "application/json"
        }
        
        # Upload audio
        upload_response = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers={"authorization": api_key},
            data=audio_bytes
        )
        upload_url = upload_response.json()['upload_url']
        
        # Request transcription
        transcript_request = {
            "audio_url": upload_url,
            "speaker_labels": True
        }
        
        transcript_response = requests.post(
            "https://api.assemblyai.com/v2/transcript",
            json=transcript_request,
            headers=headers
        )
        
        transcript_id = transcript_response.json()['id']
        
        # Poll for completion
        while True:
            polling_response = requests.get(
                f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
                headers=headers
            )
            status = polling_response.json()['status']
            
            if status == 'completed':
                return polling_response.json()['text']
            elif status == 'error':
                return None
            
            time.sleep(3)
            
    except Exception as e:
        st.error(f"Transcription error: {str(e)}")
        return None

def generate_script_with_claude(research_notes, transcriptions, api_key):
    """Generate audio tour script using Claude"""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        prompt = f"""You are an expert audio tour script writer. Based on the following research notes and initial recordings, 
create a professional, engaging audio tour script.

Research Notes and Transcriptions:
{research_notes}

Transcribed Recordings:
{chr(10).join([f"Section {i+1}: {t}" for i, t in enumerate(transcriptions)])}

Please create a comprehensive audio tour script with:
1. Clear section divisions
2. Engaging narrative flow
3. Appropriate pacing and tone
4. Natural transitions between sections
5. Interesting historical or contextual details

Format the script with clear section markers like [SECTION 1], [SECTION 2], etc.
Include timing suggestions where appropriate.
Make it conversational and engaging for listeners."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return message.content[0].text
        
    except Exception as e:
        st.error(f"Script generation error: {str(e)}")
        return None

def generate_audio_with_elevenlabs(text, voice_id, api_key, model="eleven_multilingual_v2"):
    """Generate audio using ElevenLabs API"""
    try:
        client = ElevenLabs(api_key=api_key)
        
        audio = client.text_to_speech.convert(
            voice_id=voice_id,
            optimize_streaming_latency="0",
            output_format="mp3_44100_128",
            text=text,
            model_id=model,
            voice_settings=VoiceSettings(
                stability=0.5,
                similarity_boost=0.75,
                style=0.0,
                use_speaker_boost=True,
            ),
        )
        
        # Collect audio chunks
        audio_bytes = b""
        for chunk in audio:
            if chunk:
                audio_bytes += chunk
                
        return audio_bytes
        
    except Exception as e:
        st.error(f"Audio generation error: {str(e)}")
        return None

def generate_sfx_with_elevenlabs(description, api_key, duration=5.0):
    """Generate sound effects using ElevenLabs Sound Effects API"""
    try:
        url = "https://api.elevenlabs.io/v1/sound-generation"
        
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }
        
        data = {
            "text": description,
            "duration_seconds": duration,
            "prompt_influence": 0.3
        }
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 200:
            return response.content
        else:
            st.error(f"SFX generation failed: {response.text}")
            return None
            
    except Exception as e:
        st.error(f"SFX generation error: {str(e)}")
        return None

def create_suno_music_request(description, duration=60):
    """Create a music generation request for Suno AI"""
    # Note: Suno doesn't have a public API yet, so this creates a request template
    return {
        "description": description,
        "duration": duration,
        "style": "instrumental background",
        "mood": "ambient, museum-appropriate",
        "status": "pending"
    }

def generate_resolve_xml(sections, fps=30):
    """Generate DaVinci Resolve compatible XML with markers"""
    xmeml = ET.Element('xmeml', version='4')
    
    sequence = ET.SubElement(xmeml, 'sequence')
    ET.SubElement(sequence, 'name').text = 'Audio Tour Timeline'
    
    total_duration = sections[-1]['end_time'] if sections else 0
    ET.SubElement(sequence, 'duration').text = str(timecode_to_frames(total_duration, fps))
    
    rate = ET.SubElement(sequence, 'rate')
    ET.SubElement(rate, 'timebase').text = str(fps)
    ET.SubElement(rate, 'ntsc').text = 'FALSE'
    
    timecode = ET.SubElement(sequence, 'timecode')
    rate_tc = ET.SubElement(timecode, 'rate')
    ET.SubElement(rate_tc, 'timebase').text = str(fps)
    ET.SubElement(rate_tc, 'ntsc').text = 'FALSE'
    ET.SubElement(timecode, 'string').text = '00:00:00:00'
    ET.SubElement(timecode, 'frame').text = '0'
    
    media = ET.SubElement(sequence, 'media')
    video = ET.SubElement(media, 'video')
    track = ET.SubElement(video, 'track')
    
    for i, section in enumerate(sections):
        clipitem = ET.SubElement(track, 'clipitem', id=f"clipitem-{i+1}")
        ET.SubElement(clipitem, 'name').text = section['title']
        ET.SubElement(clipitem, 'duration').text = str(timecode_to_frames(section['duration'], fps))
        
        clip_rate = ET.SubElement(clipitem, 'rate')
        ET.SubElement(clip_rate, 'timebase').text = str(fps)
        ET.SubElement(clip_rate, 'ntsc').text = 'FALSE'
        
        ET.SubElement(clipitem, 'in').text = '0'
        ET.SubElement(clipitem, 'out').text = str(timecode_to_frames(section['duration'], fps))
        ET.SubElement(clipitem, 'start').text = str(timecode_to_frames(section['start_time'], fps))
        ET.SubElement(clipitem, 'end').text = str(timecode_to_frames(section['end_time'], fps))
        
        marker = ET.SubElement(clipitem, 'marker')
        ET.SubElement(marker, 'name').text = section['title']
        ET.SubElement(marker, 'comment').text = f"Duration: {format_time(section['duration'])}"
        ET.SubElement(marker, 'in').text = str(timecode_to_frames(section['start_time'], fps))
        ET.SubElement(marker, 'out').text = str(timecode_to_frames(section['end_time'], fps))
    
    xml_string = ET.tostring(xmeml, encoding='unicode')
    dom = minidom.parseString(xml_string)
    return dom.toprettyxml(indent='  ')

# Main App UI
st.title("🎙️ Audio Tour Production Studio")
st.markdown("*Complete audio tour creation: from research to final production*")

# Sidebar for API Keys and Settings
with st.sidebar:
    st.header("⚙️ Configuration")
    
    st.session_state.project_name = st.text_input(
        "Project Name",
        value=st.session_state.project_name
    )
    
    with st.expander("🔑 API Keys", expanded=False):
        assemblyai_key = st.text_input("AssemblyAI API Key", type="password", help="For audio transcription")
        claude_key = st.text_input("Anthropic API Key", type="password", help="For script generation")
        elevenlabs_key = st.text_input("ElevenLabs API Key", type="password", help="For audio & SFX generation")
    
    with st.expander("🎵 Audio Settings", expanded=False):
        voice_id = st.text_input(
            "ElevenLabs Voice ID",
            value="21m00Tcm4TlvDq8ikWAM",
            help="Default: Rachel voice"
        )
        
        fps = st.selectbox("Timeline FPS", options=[24, 25, 30, 60], index=2)
        
        audio_model = st.selectbox(
            "ElevenLabs Model",
            options=["eleven_multilingual_v2", "eleven_monolingual_v1", "eleven_turbo_v2"],
            index=0
        )
    
    st.divider()
    
    # Workflow stage indicator
    stages = ['Recording', 'Transcription', 'Script Generation', 'Audio Production', 'Final Export']
    current_stage_idx = stages.index(st.session_state.workflow_stage.replace('_', ' ').title()) if st.session_state.workflow_stage.replace('_', ' ').title() in stages else 0
    
    st.markdown("### 📊 Workflow Progress")
    for i, stage in enumerate(stages):
        if i < current_stage_idx:
            st.markdown(f"✅ {stage}")
        elif i == current_stage_idx:
            st.markdown(f"▶️ **{stage}**")
        else:
            st.markdown(f"⭕ {stage}")

# Main Content Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🎤 Recording & Research",
    "📝 Transcription",
    "✍️ Script Generation",
    "🎵 Audio Production",
    "📦 Final Export"
])

# TAB 1: Recording & Research
with tab1:
    st.header("Step 1: Record Research Notes")
    
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
            if st.button("⏹️ Stop Lap", use_container_width=True, 
                        disabled=not st.session_state.running and st.session_state.elapsed_time == 0):
                lap_end_time = current_elapsed
                
                st.session_state.laps.append({
                    'start_time': st.session_state.current_lap_start,
                    'end_time': lap_end_time,
                    'duration': lap_end_time - st.session_state.current_lap_start,
                    'title': f"Section {len(st.session_state.laps) + 1}"
                })
                
                st.session_state.current_lap_start = lap_end_time
                st.rerun()
        
        with button_col3:
            if st.button("🔄 Reset", use_container_width=True):
                st.session_state.running = False
                st.session_state.start_time = None
                st.session_state.elapsed_time = 0
                st.session_state.laps = []
                st.session_state.current_lap_start = 0
                st.rerun()
        
        st.divider()
        
        st.subheader("🎙️ Record Audio Notes")
        st.info("Record your voice notes about each section of the tour")
        
        audio_bytes = audio_recorder(
            text="Click to record",
            recording_color="#e74c3c",
            neutral_color="#3498db",
            icon_size="2x"
        )
        
        if audio_bytes:
            st.audio(audio_bytes, format="audio/wav")
            
            if st.button("💾 Save Recording", type="primary"):
                st.session_state.recordings.append({
                    'data': audio_bytes,
                    'section': len(st.session_state.recordings) + 1,
                    'timestamp': time.time()
                })
                st.success(f"Recording {len(st.session_state.recordings)} saved!")
                st.rerun()
    
    with col2:
        st.subheader("📝 Research Notes")
        
        st.session_state.research_notes = st.text_area(
            "Manual Research Notes",
            value=st.session_state.research_notes,
            height=200,
            help="Add any additional notes or context for the AI"
        )
        
        st.divider()
        
        st.subheader("📋 Recorded Sections")
        
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
                    
                    st.write(f"**Start:** `{format_time(lap['start_time'])}`")
                    st.write(f"**End:** `{format_time(lap['end_time'])}`")
                    st.write(f"**Duration:** `{format_time(lap['duration'])}`")
                    
                    if st.button(f"🗑️ Delete", key=f"delete_{i}"):
                        st.session_state.laps.pop(i)
                        st.rerun()
        else:
            st.info("No sections recorded yet")
        
        if st.session_state.recordings:
            st.success(f"✅ {len(st.session_state.recordings)} audio recording(s) saved")

# TAB 2: Transcription
with tab2:
    st.header("Step 2: Transcribe Recordings")
    
    if not st.session_state.recordings:
        st.warning("⚠️ No recordings to transcribe. Please record audio in Step 1.")
    else:
        st.info(f"📊 {len(st.session_state.recordings)} recording(s) ready for transcription")
        
        if not assemblyai_key:
            st.error("🔑 Please enter your AssemblyAI API key in the sidebar")
        else:
            if st.button("🎯 Transcribe All Recordings", type="primary", use_container_width=True):
                with st.spinner("Transcribing audio... This may take a few minutes."):
                    progress_bar = st.progress(0)
                    
                    st.session_state.transcriptions = []
                    
                    for i, recording in enumerate(st.session_state.recordings):
                        st.write(f"Transcribing recording {i+1}/{len(st.session_state.recordings)}...")
                        
                        transcription = transcribe_audio(recording['data'], assemblyai_key)
                        
                        if transcription:
                            st.session_state.transcriptions.append({
                                'section': recording['section'],
                                'text': transcription
                            })
                        
                        progress_bar.progress((i + 1) / len(st.session_state.recordings))
                    
                    st.session_state.workflow_stage = 'transcription'
                    st.success("✅ Transcription complete!")
                    st.rerun()
        
        if st.session_state.transcriptions:
            st.divider()
            st.subheader("📄 Transcription Results")
            
            for i, trans in enumerate(st.session_state.transcriptions):
                with st.expander(f"Section {trans['section']} Transcription", expanded=False):
                    st.text_area(
                        "Transcribed Text",
                        value=trans['text'],
                        height=150,
                        key=f"trans_{i}",
                        disabled=True
                    )

# TAB 3: Script Generation
with tab3:
    st.header("Step 3: Generate Professional Script")
    
    if not st.session_state.transcriptions and not st.session_state.research_notes:
        st.warning("⚠️ Please complete transcription or add research notes first")
    else:
        if not claude_key:
            st.error("🔑 Please enter your Anthropic API key in the sidebar")
        else:
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.info("🤖 Claude will generate a professional audio tour script based on your recordings and notes")
            
            with col2:
                if st.button("✨ Generate Script", type="primary", use_container_width=True):
                    with st.spinner("Generating script with Claude AI..."):
                        script = generate_script_with_claude(
                            st.session_state.research_notes,
                            [t['text'] for t in st.session_state.transcriptions],
                            claude_key
                        )
                        
                        if script:
                            st.session_state.final_script = script
                            st.session_state.workflow_stage = 'script_generation'
                            st.success("✅ Script generated successfully!")
                            st.rerun()
            
            if st.session_state.final_script:
                st.divider()
                st.subheader("📜 Generated Script")
                
                edited_script = st.text_area(
                    "Edit the script if needed",
                    value=st.session_state.final_script,
                    height=400
                )
                
                if edited_script != st.session_state.final_script:
                    if st.button("💾 Save Edits"):
                        st.session_state.final_script = edited_script
                        st.success("Script updated!")
                
                # Download script
                st.download_button(
                    label="📥 Download Script (TXT)",
                    data=st.session_state.final_script,
                    file_name=f"{st.session_state.project_name}_script.txt",
                    mime="text/plain"
                )

# TAB 4: Audio Production
with tab4:
    st.header("Step 4: Generate Audio & Sound")
    
    if not st.session_state.final_script:
        st.warning("⚠️ Please generate a script first in Step 3")
    else:
        if not elevenlabs_key:
            st.error("🔑 Please enter your ElevenLabs API key in the sidebar")
        else:
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🎤 Generate Narration")
                
                # Split script into sections
                script_sections = st.session_state.final_script.split('[SECTION')
                script_sections = [s.strip() for s in script_sections if s.strip()]
                
                st.info(f"Script has {len(script_sections)} sections")
                
                if st.button("🎵 Generate All Audio", type="primary", use_container_width=True):
                    with st.spinner("Generating audio narration..."):
                        progress_bar = st.progress(0)
                        st.session_state.generated_audios = []
                        
                        for i, section in enumerate(script_sections):
                            # Extract section number and content
                            section_text = section.split(']', 1)[-1].strip() if ']' in section else section
                            
                            audio_bytes = generate_audio_with_elevenlabs(
                                section_text,
                                voice_id,
                                elevenlabs_key,
                                audio_model
                            )
                            
                            if audio_bytes:
                                st.session_state.generated_audios.append({
                                    'section': i + 1,
                                    'data': audio_bytes,
                                    'text': section_text[:100] + "..."
                                })
                            
                            progress_bar.progress((i + 1) / len(script_sections))
                        
                        st.session_state.workflow_stage = 'audio_production'
                        st.success(f"✅ Generated {len(st.session_state.generated_audios)} audio files!")
                        st.rerun()
            
            with col2:
                st.subheader("🔊 Sound Effects")
                
                sfx_description = st.text_input(
                    "Describe sound effect",
                    placeholder="e.g., footsteps in museum hallway"
                )
                
                sfx_duration = st.slider("Duration (seconds)", 1.0, 10.0, 5.0, 0.5)
                
                if st.button("Generate Sound Effect", use_container_width=True):
                    if sfx_description:
                        with st.spinner("Generating sound effect..."):
                            sfx_audio = generate_sfx_with_elevenlabs(
                                sfx_description,
                                elevenlabs_key,
                                sfx_duration
                            )
                            
                            if sfx_audio:
                                st.session_state.sfx_requests.append({
                                    'description': sfx_description,
                                    'duration': sfx_duration,
                                    'data': sfx_audio
                                })
                                st.success("✅ Sound effect generated!")
                                st.rerun()
                    else:
                        st.warning("Please describe the sound effect")
                
                st.divider()
                
                st.subheader("🎼 Background Music")
                
                music_description = st.text_area(
                    "Describe desired music",
                    placeholder="e.g., calm ambient music for art gallery",
                    height=100
                )
                
                music_duration = st.slider("Music duration (seconds)", 30, 180, 60)
                
                if st.button("Create Music Request", use_container_width=True):
                    if music_description:
                        request = create_suno_music_request(music_description, music_duration)
                        st.session_state.music_requests.append(request)
                        st.success("✅ Music request created! (Manual generation needed on Suno AI)")
                        st.rerun()
            
            # Display generated content
            if st.session_state.generated_audios:
                st.divider()
                st.subheader("🎧 Generated Audio Files")
                
                for i, audio in enumerate(st.session_state.generated_audios):
                    with st.expander(f"Section {audio['section']}", expanded=False):
                        st.write(f"**Preview:** {audio['text']}")
                        st.audio(audio['data'], format="audio/mp3")
                        st.download_button(
                            label=f"📥 Download Section {audio['section']}",
                            data=audio['data'],
                            file_name=f"section_{audio['section']}.mp3",
                            mime="audio/mp3",
                            key=f"download_audio_{i}"
                        )
            
            if st.session_state.sfx_requests:
                st.divider()
                st.subheader("🔊 Generated Sound Effects")
                
                for i, sfx in enumerate(st.session_state.sfx_requests):
                    with st.expander(f"SFX: {sfx['description']}", expanded=False):
                        st.audio(sfx['data'], format="audio/mp3")
                        st.download_button(
                            label="📥 Download SFX",
                            data=sfx['data'],
                            file_name=f"sfx_{i+1}.mp3",
                            mime="audio/mp3",
                            key=f"download_sfx_{i}"
                        )

# TAB 5: Final Export
with tab5:
    st.header("Step 5: Export Final Package")
    
    if not st.session_state.generated_audios:
        st.warning("⚠️ Please generate audio files first in Step 4")
    else:
        st.success("✅ Ready to export your complete audio tour package!")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📦 Export Package Includes:")
            st.markdown(f"""
            - ✅ **{len(st.session_state.generated_audios)}** Audio narration files
            - ✅ **{len(st.session_state.sfx_requests)}** Sound effects
            - ✅ **{len(st.session_state.music_requests)}** Music requests
            - ✅ **1** DaVinci Resolve XML timeline
            - ✅ **1** Complete script (TXT)
            - ✅ **1** Project summary (JSON)
            """)
        
        with col2:
            st.subheader("⚙️ Export Settings")
            
            include_xml = st.checkbox("Include XML Timeline", value=True)
            include_script = st.checkbox("Include Script", value=True)
            include_metadata = st.checkbox("Include Project Metadata", value=True)
        
        st.divider()
        
        # Individual downloads
        st.subheader("📥 Individual Downloads")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.session_state.laps and include_xml:
                xml_content = generate_resolve_xml(st.session_state.laps, fps)
                st.download_button(
                    label="⬇️ Download XML Timeline",
                    data=xml_content,
                    file_name=f"{st.session_state.project_name}_timeline.xml",
                    mime="application/xml",
                    use_container_width=True
                )
        
        with col2:
            if st.session_state.final_script and include_script:
                st.download_button(
                    label="⬇️ Download Script",
                    data=st.session_state.final_script,
                    file_name=f"{st.session_state.project_name}_script.txt",
                    mime="text/plain",
                    use_container_width=True
                )
        
        with col3:
            if include_metadata:
                metadata = {
                    'project_name': st.session_state.project_name,
                    'sections': len(st.session_state.laps),
                    'audio_files': len(st.session_state.generated_audios),
                    'sound_effects': len(st.session_state.sfx_requests),
                    'music_requests': st.session_state.music_requests,
                    'total_duration': format_time(st.session_state.laps[-1]['end_time']) if st.session_state.laps else "0:00:00",
                    'created': time.strftime('%Y-%m-%d %H:%M:%S')
                }
                
                st.download_button(
                    label="⬇️ Download Metadata",
                    data=json.dumps(metadata, indent=2),
                    file_name=f"{st.session_state.project_name}_metadata.json",
                    mime="application/json",
                    use_container_width=True
                )
        
        # Music requests summary
        if st.session_state.music_requests:
            st.divider()
            st.subheader("🎼 Music Generation Requests for Suno AI")
            st.info("These requests need to be manually created on Suno AI platform")
            
            for i, req in enumerate(st.session_state.music_requests):
                with st.expander(f"Music Request {i+1}", expanded=False):
                    st.markdown(f"""
                    **Description:** {req['description']}  
                    **Duration:** {req['duration']} seconds  
                    **Style:** {req['style']}  
                    **Mood:** {req['mood']}  
                    **Status:** {req['status']}
                    """)
        
        # Timeline preview
        if st.session_state.laps:
            st.divider()
            st.subheader("📊 Timeline Preview")
            
            with st.expander("View Complete Timeline", expanded=False):
                for i, lap in enumerate(st.session_state.laps):
                    st.markdown(f"""
                    **{i+1}. {lap['title']}**
                    - Start: `{format_time(lap['start_time'])}` (Frame: {timecode_to_frames(lap['start_time'], fps)})
                    - End: `{format_time(lap['end_time'])}` (Frame: {timecode_to_frames(lap['end_time'], fps)})
                    - Duration: `{format_time(lap['duration'])}`
                    """)

# Auto-refresh for running timer
if st.session_state.running:
    time.sleep(0.1)
    st.rerun()
