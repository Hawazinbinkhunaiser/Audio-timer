import streamlit as st
import time
from datetime import timedelta
import xml.etree.ElementTree as ET
from xml.dom import minidom
import io

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

def generate_resolve_xml(laps, fps=30):
    """Generate DaVinci Resolve compatible XML with markers"""
    # Create XML structure
    xmeml = ET.Element('xmeml', version='4')
    
    # Create sequence
    sequence = ET.SubElement(xmeml, 'sequence')
    ET.SubElement(sequence, 'name').text = 'Audio Tour Timeline'
    ET.SubElement(sequence, 'duration').text = str(timecode_to_frames(laps[-1]['end_time'], fps) if laps else 0)
    
    # Rate settings
    rate = ET.SubElement(sequence, 'rate')
    ET.SubElement(rate, 'timebase').text = str(fps)
    ET.SubElement(rate, 'ntsc').text = 'FALSE'
    
    # Timecode
    timecode = ET.SubElement(sequence, 'timecode')
    ET.SubElement(timecode, 'rate')
    rate_tc = timecode.find('rate')
    ET.SubElement(rate_tc, 'timebase').text = str(fps)
    ET.SubElement(rate_tc, 'ntsc').text = 'FALSE'
    ET.SubElement(timecode, 'string').text = '00:00:00:00'
    ET.SubElement(timecode, 'frame').text = '0'
    
    # Media
    media = ET.SubElement(sequence, 'media')
    
    # Video track
    video = ET.SubElement(media, 'video')
    track = ET.SubElement(video, 'track')
    
    # Add markers for each lap
    for i, lap in enumerate(laps):
        # Create a clip item for each section
        clipitem = ET.SubElement(track, 'clipitem', id=f"clipitem-{i+1}")
        ET.SubElement(clipitem, 'name').text = lap['title']
        ET.SubElement(clipitem, 'duration').text = str(timecode_to_frames(lap['duration'], fps))
        
        # Rate
        clip_rate = ET.SubElement(clipitem, 'rate')
        ET.SubElement(clip_rate, 'timebase').text = str(fps)
        ET.SubElement(clip_rate, 'ntsc').text = 'FALSE'
        
        # In/Out points
        ET.SubElement(clipitem, 'in').text = '0'
        ET.SubElement(clipitem, 'out').text = str(timecode_to_frames(lap['duration'], fps))
        ET.SubElement(clipitem, 'start').text = str(timecode_to_frames(lap['start_time'], fps))
        ET.SubElement(clipitem, 'end').text = str(timecode_to_frames(lap['end_time'], fps))
        
        # Add marker
        marker = ET.SubElement(clipitem, 'marker')
        ET.SubElement(marker, 'name').text = lap['title']
        ET.SubElement(marker, 'comment').text = f"Duration: {format_time(lap['duration'])}"
        ET.SubElement(marker, 'in').text = str(timecode_to_frames(lap['start_time'], fps))
        ET.SubElement(marker, 'out').text = str(timecode_to_frames(lap['end_time'], fps))
    
    # Pretty print XML
    xml_string = ET.tostring(xmeml, encoding='unicode')
    dom = minidom.parseString(xml_string)
    return dom.toprettyxml(indent='  ')

# Page config
st.set_page_config(
    page_title="Audio Tour Timer",
    page_icon="🎙️",
    layout="wide"
)

# Title and description
st.title("🎙️ Audio Tour Timestamp Manager")
st.markdown("""
Create precise timestamps for your audio tour sections. Start the timer when entering each space, 
create laps for each section, and export to XML for DaVinci Resolve.
""")

# Create two columns
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("⏱️ Timer Control")
    
    # Calculate current time
    if st.session_state.running and st.session_state.start_time:
        current_elapsed = st.session_state.elapsed_time + (time.time() - st.session_state.start_time)
    else:
        current_elapsed = st.session_state.elapsed_time
    
    # Display timer
    timer_display = st.empty()
    timer_display.markdown(f"## `{format_time(current_elapsed)}`")
    
    # Control buttons
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
            # Store the current time as lap end
            lap_end_time = current_elapsed
            
            # Create lap entry (title will be added below)
            st.session_state.laps.append({
                'start_time': st.session_state.current_lap_start,
                'end_time': lap_end_time,
                'duration': lap_end_time - st.session_state.current_lap_start,
                'title': f"Section {len(st.session_state.laps) + 1}"
            })
            
            # Update current lap start for next lap
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
        
        # Display and edit laps
        for i, lap in enumerate(st.session_state.laps):
            with st.expander(f"Section {i+1}: {lap['title']}", expanded=False):
                # Edit title
                new_title = st.text_input(
                    "Section Title",
                    value=lap['title'],
                    key=f"title_{i}"
                )
                st.session_state.laps[i]['title'] = new_title
                
                # Display times
                st.write(f"**Start:** `{format_time(lap['start_time'])}`")
                st.write(f"**End:** `{format_time(lap['end_time'])}`")
                st.write(f"**Duration:** `{format_time(lap['duration'])}`")
                
                # Delete button
                if st.button(f"🗑️ Delete Section {i+1}", key=f"delete_{i}"):
                    st.session_state.laps.pop(i)
                    st.rerun()
    else:
        st.info("No sections recorded yet. Start the timer and create your first lap!")

# Export section
st.divider()
st.subheader("📤 Export Timeline")

if st.session_state.laps:
    export_col1, export_col2 = st.columns(2)
    
    with export_col1:
        fps = st.selectbox(
            "Frame Rate (FPS)",
            options=[24, 25, 30, 60],
            index=2,
            help="Select the frame rate for your DaVinci Resolve project"
        )
    
    with export_col2:
        st.write("")  # Spacing
        st.write("")  # Spacing
        
        # Generate XML
        xml_content = generate_resolve_xml(st.session_state.laps, fps)
        
        # Download button
        st.download_button(
            label="⬇️ Download XML for DaVinci Resolve",
            data=xml_content,
            file_name="audio_tour_timeline.xml",
            mime="application/xml",
            use_container_width=True,
            type="primary"
        )
    
    # Preview
    with st.expander("📄 Preview Timeline Summary"):
        st.markdown("### Timeline Overview")
        for i, lap in enumerate(st.session_state.laps):
            st.markdown(f"""
            **{i+1}. {lap['title']}**
            - Start: `{format_time(lap['start_time'])}` (Frame: {timecode_to_frames(lap['start_time'], fps)})
            - End: `{format_time(lap['end_time'])}` (Frame: {timecode_to_frames(lap['end_time'], fps)})
            - Duration: `{format_time(lap['duration'])}`
            """)
else:
    st.info("Record some sections to enable XML export.")

# Instructions
with st.expander("ℹ️ How to Use"):
    st.markdown("""
    ### Step-by-Step Guide:
    
    1. **Start Timer**: Click the "▶️ Start" button when you enter the first space
    2. **Create Sections**: Click "⏹️ Stop Lap" at the end of each audio tour section
    3. **Edit Titles**: Expand each section and give it a meaningful title
    4. **Export**: Select your frame rate and download the XML file
    5. **Import to DaVinci Resolve**: 
       - Open DaVinci Resolve
       - Go to File → Import → Timeline
       - Select the downloaded XML file
       - Your sections will appear as markers/clips on the timeline
    
    ### Tips:
    - You can pause the timer if needed
    - Edit section titles to match your audio content
    - Delete unwanted sections using the delete button
    - The XML file contains both markers and clip information for easy editing
    """)

# Auto-refresh for running timer
if st.session_state.running:
    time.sleep(0.1)
    st.rerun()
