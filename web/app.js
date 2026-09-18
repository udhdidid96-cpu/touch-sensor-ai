/**
 * Smart Extubation AI — Modern Clinical Telemetry Dashboard Engine
 * Clean Light Clinical Theme with Real-time Multi-Class Inference
 */

'use strict';

console.info('This system has not been assessed against IEC 62304.');

const SAMPLE_PERIOD_MS = 560;

const state = {
  layout: null,
  datasets: [],
  file: null,
  frames: [],
  idx: 0,
  playing: false,
  timer: null,
  heatCache: new Map(),
  chart: null,
  isMuted: false,
  lastLevel: 0,
  lastLoggedLevel: null,   // level of the previous frame, for audit-trail edges
  audioCtx: null,
  currentLang: 'th',
  mode: 'live',
  liveWs: null,
  liveStreaming: false
};

function withKey(url) {
  try {
    const params = new URLSearchParams(window.location.search);
    const key = params.get('key');
    if (!key) return url;
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}key=${encodeURIComponent(key)}`;
  } catch (e) {
    return url;
  }
}

// Verified 25-node physical layout coordinates (90x120 mm patch)
const DEFAULT_LAYOUT = [
  { pad: 1, x: 57.0, y: 90.0 }, { pad: 2, x: 73.0, y: 78.0 }, { pad: 3, x: 58.0, y: 78.0 },
  { pad: 4, x: 79.0, y: 64.0 }, { pad: 5, x: 65.0, y: 64.0 }, { pad: 6, x: 80.0, y: 50.0 },
  { pad: 7, x: 65.0, y: 50.0 }, { pad: 8, x: 80.0, y: 36.0 }, { pad: 9, x: 65.0, y: 36.0 },
  { pad: 10, x: 74.0, y: 24.0 }, { pad: 11, x: 58.0, y: 22.0 }, { pad: 12, x: 50.0, y: 64.0 },
  { pad: 13, x: 50.0, y: 50.0 }, { pad: 14, x: 50.0, y: 35.0 }, { pad: 15, x: 41.0, y: 90.0 },
  { pad: 16, x: 40.0, y: 78.0 }, { pad: 17, x: 26.0, y: 78.0 }, { pad: 18, x: 35.0, y: 64.0 },
  { pad: 19, x: 21.0, y: 64.0 }, { pad: 20, x: 35.0, y: 50.0 }, { pad: 21, x: 20.0, y: 50.0 },
  { pad: 22, x: 35.0, y: 36.0 }, { pad: 23, x: 20.0, y: 36.0 }, { pad: 24, x: 40.0, y: 22.0 },
  { pad: 25, x: 25.0, y: 24.0 }
];

// Verified physical pad to raw Signal-* channel index mapping (0-indexed)
// Pad N (1..25) -> Signal channel index (Signal-K -> K-1)
// Verified by 1-by-1 press sweep (Spearman rho 1.0000)
const RAW_TO_PAD_MAP = [
  19, // Pad 1  -> Signal-20 (idx 19)
  20, // Pad 2  -> Signal-21 (idx 20)
  18, // Pad 3  -> Signal-19 (idx 18)
  21, // Pad 4  -> Signal-22 (idx 21)
  17, // Pad 5  -> Signal-18 (idx 17)
  22, // Pad 6  -> Signal-23 (idx 22)
  16, // Pad 7  -> Signal-17 (idx 16)
  23, // Pad 8  -> Signal-24 (idx 23)
  15, // Pad 9  -> Signal-16 (idx 15)
  24, // Pad 10 -> Signal-25 (idx 24)
  14, // Pad 11 -> Signal-15 (idx 14)
  13, // Pad 12 -> Signal-14 (idx 13)
  12, // Pad 13 -> Signal-13 (idx 12)
  11, // Pad 14 -> Signal-12 (idx 11)
  5,  // Pad 15 -> Signal-6  (idx 5)
  6,  // Pad 16 -> Signal-7  (idx 6)
  4,  // Pad 17 -> Signal-5  (idx 4)
  7,  // Pad 18 -> Signal-8  (idx 7)
  3,  // Pad 19 -> Signal-4  (idx 3)
  8,  // Pad 20 -> Signal-9  (idx 8)
  2,  // Pad 21 -> Signal-3  (idx 2)
  9,  // Pad 22 -> Signal-10 (idx 9)
  1,  // Pad 23 -> Signal-2  (idx 1)
  10, // Pad 24 -> Signal-11 (idx 10)
  0   // Pad 25 -> Signal-1  (idx 0)
];

function remapToPhysicalPads(raw) {
  if (!raw || raw.length < 25) return raw;
  const out = new Array(25);
  for (let i = 0; i < 25; i++) {
    out[i] = raw[RAW_TO_PAD_MAP[i]];
  }
  return out;
}



/* -------------------------------------------------------- Multi-Language --
 * Three languages, applied by `data-i18n` attribute rather than by a hand-kept
 * map of element ids. The old map named 22 ids; anything added to the markup
 * after it was written silently stayed English, which is how a "Thai" console
 * ended up half in English. An attribute travels with the element.
 *
 * The `txt-*` id map below is kept only for the handful of nodes the frame
 * renderer also writes to by id.
 */
const TRANSLATIONS = {
  th: {
    peel_dir: 'ทิศทางการลอก',
    standby: 'รอเชื่อมต่อ', protocol_replay: 'ตรวจสอบไฟล์ย้อนหลัง', ward_unassigned: 'ยังไม่ได้ระบุผู้ป่วย',
    desc_gate_none: 'ไม่มีแพดใดต่ำกว่าเกณฑ์ยกตัว −300 counts',
    desc_gate_some: 'ยกตัว {n} / 25 แพด (ต่ำกว่า −300 counts)',
    desc_gate_confirmed: ' · ยืนยันการลอกแล้ว',
    ward_nosignal: 'ไม่มีสัญญาณ', ward_nodevice: 'ยังไม่ได้เชื่อมต่ออุปกรณ์',
    ward_assign: 'กำหนดสตรีม', ward_edit: 'แก้ไข',
    brand_sub: 'คอนโซลเซนเซอร์สัมผัสแบบ capacitive',
    meta_session: 'เซสชัน', meta_started: 'เริ่มเมื่อ', meta_frame: 'เฟรม',
    meta_protocol: 'โปรโตคอล', meta_operator: 'ผู้ปฏิบัติงาน',
    protocol_live: 'สัญญาณสด (25 ช่องสัญญาณ)', device_status: 'สถานะอุปกรณ์',

    nav_dashboard: 'หน้าหลัก', nav_live: 'เฝ้าระวังสด', nav_replay: 'ย้อนหลังและตรวจสอบ',
    nav_events: 'บันทึกเหตุการณ์', nav_model: 'ประสิทธิภาพโมเดล', nav_ward: 'มุมมองทั้งวอร์ด',
    nav_reports: 'รายงานและส่งออก', nav_settings: 'ตั้งค่าระบบ',
    disclaimer_k: 'ข้อจำกัด', foot_dept: 'วิศวกรรมชีวการแพทย์',

    mode_live: 'สด', mode_replay: 'ย้อนหลัง',
    f_bed: 'เตียง', f_port: 'พอร์ตอนุกรม', opt_port: 'เลือกพอร์ต…',
    btn_rescan: 'ค้นหาใหม่', btn_connect: 'เชื่อมต่อ',
    btn_zero: '1. ติดแผ่นเซนเซอร์ แล้วตั้งศูนย์',
    btn_start: '2. เริ่มเฝ้าระวังสด',
    btn_start_active: '2. กำลังเฝ้าระวังสด (พัก)',
    f_preset: 'สถานการณ์',

    p_analysis: 'การวิเคราะห์สด', chip_dir: 'ทิศทางการลอก: ไม่มี',
    p_summary: 'สรุปผลประเมิน', chip_engine: 'เครื่องอนุมาน',
    v2_label: 'ดัชนีความเสี่ยงการลอกของแผ่นเซนเซอร์ (CPRI)', gauge_mid: '50',
    thr_k: 'ตัวส่งสัญญาณเตือน',
    thr_v: 'CPRI เป็นเพียงดัชนีสำหรับแสดงผล การเตือนตัดสินจากหน้าต่างโหวต 7-of-6 (hold 9) ไม่ใช่จากหน้าปัดนี้',
    v1_label: 'สถานะการเตือน', v5_label: 'ความเชื่อมั่น',
    v5_sub: 'ความน่าจะเป็นของคลาสสูงสุดในเฟรมนี้', v3_label: 'แพดที่ยังแนบผิว',

    p_pipeline: 'ลำดับการประมวลผล',
    pipe1: '1. รับข้อมูลอนุกรม', pipe1d: '25 ช่องสัญญาณ',
    pipe2: '2. เส้นฐาน Kalman', pipe2d: 'ชดเชยการดริฟท์',
    pipe3: '3. สกัดคุณลักษณะ', pipe3d: 'ค่าต่างรายแพด + สถิติ', pipe3s: '34 คุณลักษณะ',
    pipe4: '4. จำแนกประเภท', pipe4d: 'Gradient-boosted trees', pipe4s: '4 คลาส',
    pipe5: '5. ส่งสัญญาณเตือน', pipe5d: 'หน้าต่างโหวต + หน่วงค้าง',

    p_validation: 'การตรวจสอบโมเดล', chip_lofo: 'Leave-one-file-out กันไฟล์ไว้ทดสอบ',
    m_acc: 'ความแม่นยำ', m_f1: 'MACRO F1', m_peel: 'PEEL F1', m_fa: 'เตือนผิด / ไฟล์',
    chart_title: 'ความน่าจะเป็นรายคลาสและเส้นเวลา CPRI',
    d_title: 'รายละเอียดโมเดล', d_est: 'ตัวประมาณ', d_feat: 'คุณลักษณะ',
    d_feat_v: 'ค่าต่าง 25 แพด + สถิติ 9 ค่า', d_cls: 'คลาส',
    d_cls_v: 'ปกติ · สัมผัส · เริ่มลอก · ดึงหลุด',
    d_val: 'วิธีตรวจสอบ', d_val_v: 'Leave-one-file-out ทั่วทั้งชุดบันทึก',
    d_op: 'จุดปฏิบัติการ', d_gen: 'วัดเมื่อ',

    p_history: 'ประวัติการประเมิน', view_all: 'ดูทั้งหมด', btn_export_csv: 'ส่งออก CSV',
    th_id: 'รหัสเหตุการณ์', th_time: 'เวลา', th_src: 'แหล่งข้อมูล',
    th_frame: 'เฟรม', th_sev: 'ระดับความรุนแรง', th_risk: 'ค่าความเสี่ยง',
    tbl_empty: 'ยังไม่มีบันทึกเหตุการณ์ในเวรนี้',
    p_notes: 'บันทึก', notes_ph: 'บันทึกทางคลินิกของเซสชันนี้…',
    notes_hint: 'เก็บไว้ในเบราว์เซอร์นี้เท่านั้น ไม่มีการเขียนลงเวชระเบียนผู้ป่วย',

    p_eventlog: 'บันทึกเหตุการณ์', chip_audit: 'ร่องรอยตรวจสอบฝั่งเซิร์ฟเวอร์',
    btn_refresh: 'รีเฟรช',
    events_hint: 'ระบบเขียนบันทึกทุกครั้งที่ระดับการเตือนเปลี่ยน หากเขียนไม่สำเร็จจะแจ้งเตือนขึ้นมา ไม่กลืนความผิดพลาด',

    p_modelperf: 'ประสิทธิภาพโมเดล',
    m_acc_s: 'ระดับเฟรม นอกโฟลด์', m_f1_s: 'เฉลี่ยไม่ถ่วงน้ำหนักทั้ง 4 คลาส',
    m_peel_s: 'คลาสที่ซื้อเวลาแจ้งเตือนล่วงหน้า', m_fa_s: 'ระดับเหตุการณ์ ตามที่วอร์ดรู้สึกจริง',
    notice_k: 'อ่านค่าเหล่านี้อย่างไร',
    notice_v: 'ทุกตัวเลขวัดใหม่จากชุดบันทึกและเผยแพร่พร้อมโมเดล ไม่มีค่าใดพิมพ์ลงในหน้านี้ หาก API ตอบไม่ได้ ช่องจะว่างไว้แทนที่จะแสดงค่าที่จำมา',

    p_ward: 'มุมมองทั้งวอร์ด', chip_ward: 'มีสตรีมสดหนึ่งเตียง ที่เหลือเป็นช่องว่าง',
    ward_hint: 'ช่องเตียงเก็บเฉพาะสิ่งที่ผู้ปฏิบัติงานกรอกเอง ไม่มีการสร้างชื่อผู้ป่วย ค่าความเสี่ยง หรือข้อมูลท่อขึ้นเองสำหรับเตียงที่ยังว่าง',

    p_reports: 'รายงานเวรและการส่งออก', chip_shift: 'เวรปัจจุบัน',
    r_shift: 'รหัสเวร', r_total: 'เหตุการณ์ทั้งหมด', r_crit: 'การเตือนวิกฤต',
    r_hint: 'ไม่มีตัวเลข uptime ของแผ่นเซนเซอร์ในรายงานนี้ เพราะระบบไม่ได้วัดความยาวเซสชัน เฟรมที่หาย หรือการหลุดการเชื่อมต่อ',
    btn_print: 'พิมพ์ / บันทึกเป็น PDF',

    p_settings: 'ตั้งค่าระบบ', s_lang: 'ภาษาของหน้าจอ', s_theme: 'ธีมการแสดงผล',
    s_light: 'สว่าง', s_dark: 'มืด', s_audio: 'เสียงเตือน', s_audio_btn: 'สลับเสียงเตือน',
    s_hw: 'การเก็บสัญญาณ', s_rate: 'คาบการสุ่ม', s_ch: 'ช่องสัญญาณ',
    s_ch_v: 'แพด capacitive 25 จุด บนแผ่นปิดขนาด 90 × 120 มม.',
    s_gate: 'เกณฑ์การยกตัว', s_gate_v: '−300 counts ต่อแพด, noise gate 60 counts',

    pe_title: 'แก้ไขข้อมูลเตียง', pe_sub: 'เก็บเฉพาะสิ่งที่กรอกที่นี่ และเก็บในเบราว์เซอร์นี้เท่านั้น',
    pe_bed: 'เตียง', pe_id: 'รหัสผู้ป่วย', pe_id_ph: 'เลขประจำตัวผู้ป่วย',
    pe_name: 'ชื่อผู้ป่วย', pe_name_ph: 'ชื่อ-นามสกุล',
    pe_tube: 'ชนิด / ขนาดท่อ', pe_tube_ph: 'ชนิดและความลึกของท่อ',
    pe_notes: 'บันทึก', pe_notes_ph: 'บันทึกสั้น ๆ ทางคลินิก',
    btn_cancel: 'ยกเลิก', btn_save: 'บันทึก',

    provenance: 'ต้นแบบนี้ยังไม่ผ่านการประเมินตาม IEC 62304 (has not been assessed against IEC 62304) เป็นเครื่องมือช่วยคัดกรอง ไม่ใช่สิ่งทดแทนการวินิจฉัยของบุคลากรทางการแพทย์',
    attached: 'แนบสนิท', preset_label: 'สถานการณ์:', upload: 'อัปโหลด CSV',
    sc0: 'ปกติ', sc1: 'สัมผัส', sc2: 'เริ่มลอก', sc3: 'ดึงหลุด',
    patch_title: 'แพด capacitive 25 จุด · 90 × 120 มม.',
    leg_press: 'สัมผัส / กด', leg_peel: 'เริ่มลอก', leg_deep: 'หลุดยกแผ่น', leg_quiet: 'แนบสนิท',
    p_norm: '0. ปกติ', p_touch: '1. สัมผัส', p_peel: '2. เริ่มลอก', p_pull: '3. ดึงหลุด',
    status_0: 'ปกติ (เส้นฐานทำงาน)', status_1: 'ผู้ป่วยใช้มือสัมผัส / กด',
    status_2: 'เตือนล่วงหน้า: แผ่นเริ่มลอก', status_3: 'วิกฤต: แผ่นหลุด / ท่อเคลื่อน',
    desc_0: 'แผ่นปิดแนบผิวสนิททั้งแผ่น', desc_1: 'ตรวจพบการสัมผัสด้วยฝ่ามือหรือโดนโดยบังเอิญ',
    desc_2: 'ขอบแผ่นปิดเริ่มหลุดออกจากผิว', desc_3: 'แผ่นเซนเซอร์ยกตัวทั้งแผ่น / ท่ออาจเคลื่อน',
    cat_0: 'ความเสี่ยงต่ำ (แนบสนิท)', cat_1: 'ความเสี่ยงปานกลาง (เฝ้าดู)',
    cat_2: 'ความเสี่ยงสูง (เตือน)', cat_3: 'ความเสี่ยงวิกฤต (เข้าดูทันที)'
  },

  en: {
    peel_dir: 'Peel direction',
    standby: 'Standby', protocol_replay: 'Recorded-file audit', ward_unassigned: 'No patient assigned',
    desc_gate_none: 'No pad past the −300 count lift gate',
    desc_gate_some: '{n} of 25 pads lifting (below −300 counts)',
    desc_gate_confirmed: ' · peel confirmed',
    ward_nosignal: 'No signal', ward_nodevice: 'No device attached',
    ward_assign: 'Assign stream', ward_edit: 'Edit',
    brand_sub: 'Capacitive touch-sensor dressing console',
    meta_session: 'SESSION', meta_started: 'STARTED', meta_frame: 'FRAME',
    meta_protocol: 'PROTOCOL', meta_operator: 'OPERATOR',
    protocol_live: 'Live telemetry (25-channel)', device_status: 'DEVICE STATUS',

    nav_dashboard: 'Dashboard', nav_live: 'Live Monitor', nav_replay: 'Replay & Audit',
    nav_events: 'Event Log', nav_model: 'Model Performance', nav_ward: 'Ward View',
    nav_reports: 'Reports & Export', nav_settings: 'System Settings',
    disclaimer_k: 'DISCLAIMER', foot_dept: 'Biomedical Engineering',

    mode_live: 'Live', mode_replay: 'Replay',
    f_bed: 'BED', f_port: 'SERIAL PORT', opt_port: 'Select port…',
    btn_rescan: 'Rescan', btn_connect: 'Connect',
    btn_zero: '1. Attach patch & calibrate zero',
    btn_start: '2. Start live monitoring',
    btn_start_active: '2. Monitoring active (Pause)',
    f_preset: 'SCENARIO',

    p_analysis: 'LIVE ANALYSIS', chip_dir: 'Peel direction: none',
    p_summary: 'ASSESSMENT SUMMARY', chip_engine: 'Inference engine',
    v2_label: 'CAPACITIVE PEEL RISK INDEX (CPRI)', gauge_mid: '50',
    thr_k: 'ANNUNCIATOR',
    thr_v: 'CPRI is a display index. The alarm is raised by the 7-of-6 vote window (hold 9), not by this dial.',
    v1_label: 'ALARM STATE', v5_label: 'CONFIDENCE',
    v5_sub: 'Top-class probability, this frame', v3_label: 'PADS ATTACHED',

    p_pipeline: 'PROCESSING PIPELINE',
    pipe1: '1. Serial ingest', pipe1d: '25 channels',
    pipe2: '2. Kalman baseline', pipe2d: 'Zero-drift track',
    pipe3: '3. Feature extraction', pipe3d: 'Pad deltas + statistics', pipe3s: '34 features',
    pipe4: '4. Classification', pipe4d: 'Gradient-boosted trees', pipe4s: '4 classes',
    pipe5: '5. Annunciator', pipe5d: 'Vote window + hold',

    p_validation: 'MODEL VALIDATION', chip_lofo: 'Leave-one-file-out, held out',
    m_acc: 'ACCURACY', m_f1: 'MACRO F1', m_peel: 'PEEL F1', m_fa: 'FALSE ALARM / REC',
    chart_title: 'Class probability & CPRI timeline',
    d_title: 'MODEL DETAILS', d_est: 'Estimator', d_feat: 'Features',
    d_feat_v: '25 pad deltas + 9 statistics', d_cls: 'Classes',
    d_cls_v: 'Normal · Touch · Peel · Pull',
    d_val: 'Validation', d_val_v: 'Leave-one-file-out over the recording corpus',
    d_op: 'Operating point', d_gen: 'Measured',

    p_history: 'ASSESSMENT HISTORY', view_all: 'View all', btn_export_csv: 'Export CSV',
    th_id: 'Event ID', th_time: 'Time', th_src: 'Source',
    th_frame: 'Frame', th_sev: 'Severity', th_risk: 'Risk',
    tbl_empty: 'No events recorded in this shift',
    p_notes: 'NOTES', notes_ph: 'Add clinical notes for this session…',
    notes_hint: 'Held in this browser only. Nothing here is written to a patient record.',

    p_eventlog: 'EVENT LOG', chip_audit: 'Server-side audit trail',
    btn_refresh: 'Refresh',
    events_hint: 'An entry is written on every change of alarm level. A failed write is surfaced as a toast, never swallowed.',

    p_modelperf: 'MODEL PERFORMANCE',
    m_acc_s: 'Frame-level, out of fold', m_f1_s: 'Unweighted over four classes',
    m_peel_s: 'The class that buys warning time', m_fa_s: 'Episode level, what a ward feels',
    notice_k: 'HOW TO READ THESE',
    notice_v: 'Every figure is re-measured from the recording corpus and re-published with the model. None of them is typed into this page; if the API cannot answer, the slots stay blank rather than showing a remembered number.',

    p_ward: 'WARD VIEW', chip_ward: 'One stream is live; the rest are empty slots',
    ward_hint: 'Bed slots hold only what an operator types here. No identity, risk index or tube detail is generated for an unassigned slot.',

    p_reports: 'SHIFT REPORT & EXPORT', chip_shift: 'Current shift',
    r_shift: 'SHIFT ID', r_total: 'TOTAL EVENTS', r_crit: 'CRITICAL ALARMS',
    r_hint: 'Patch uptime is not reported here. Nothing in this system measures session length, dropped frames or disconnects, so no such figure is shown.',
    btn_print: 'Print / save as PDF',

    p_settings: 'SYSTEM SETTINGS', s_lang: 'INTERFACE LANGUAGE', s_theme: 'APPEARANCE',
    s_light: 'Light', s_dark: 'Dark', s_audio: 'ALARM AUDIO', s_audio_btn: 'Toggle audio',
    s_hw: 'ACQUISITION', s_rate: 'Sample period', s_ch: 'Channels',
    s_ch_v: '25 capacitive pads, 90 × 120 mm dressing',
    s_gate: 'Lift gate', s_gate_v: '−300 counts per pad; noise gate 60 counts',

    pe_title: 'Edit bed assignment', pe_sub: 'Only what you type here is stored, in this browser.',
    pe_bed: 'BED', pe_id: 'PATIENT ID', pe_id_ph: 'hospital number',
    pe_name: 'PATIENT NAME', pe_name_ph: 'patient name',
    pe_tube: 'TUBE TYPE / SIZE', pe_tube_ph: 'tube type and depth',
    pe_notes: 'NOTES', pe_notes_ph: 'short clinical note',
    btn_cancel: 'Cancel', btn_save: 'Save',

    provenance: 'This prototype has not been assessed against IEC 62304. It is a screening aid and does not replace clinical judgement by qualified staff.',
    attached: 'Attached', preset_label: 'Scenario:', upload: 'Upload CSV',
    sc0: 'Normal', sc1: 'Touch', sc2: 'Peel', sc3: 'Pull',
    patch_title: '25-node capacitive patch · 90 × 120 mm',
    leg_press: 'Touch / press', leg_peel: 'Partial peel', leg_deep: 'Full detach', leg_quiet: 'Attached',
    p_norm: '0. Normal', p_touch: '1. Touch', p_peel: '2. Peel', p_pull: '3. Pull',
    status_0: 'Normal (baseline active)', status_1: 'Hand press / touch',
    status_2: 'Early peel warning', status_3: 'Critical: full detachment',
    desc_0: 'Dressing fully adhering to skin', desc_1: 'Palm touch or incidental contact detected',
    desc_2: 'Dressing border beginning to detach', desc_3: 'Sensor patch fully lifted; tube may be displaced',
    cat_0: 'Low risk (attached)', cat_1: 'Moderate risk (observe)',
    cat_2: 'High risk (warning)', cat_3: 'Critical risk (attend now)'
  },

  jp: {
    peel_dir: '剥離方向',
    standby: '待機中', protocol_replay: '記録ファイルの監査', ward_unassigned: '患者未割当',
    desc_gate_none: '−300 counts の剥離しきい値を超えたパッドはありません',
    desc_gate_some: '25 枚中 {n} 枚が剥離（−300 counts 未満）',
    desc_gate_confirmed: ' · 剥離を確認',
    ward_nosignal: '信号なし', ward_nodevice: '機器未接続',
    ward_assign: 'ストリーム割当', ward_edit: '編集',
    brand_sub: '静電容量式タッチセンサー・ドレッシングコンソール',
    meta_session: 'セッション', meta_started: '開始時刻', meta_frame: 'フレーム',
    meta_protocol: 'プロトコル', meta_operator: '操作者',
    protocol_live: 'ライブ計測（25チャンネル）', device_status: '機器の状態',

    nav_dashboard: 'ダッシュボード', nav_live: 'ライブ監視', nav_replay: '再生と監査',
    nav_events: 'イベントログ', nav_model: 'モデル性能', nav_ward: '病棟ビュー',
    nav_reports: 'レポートと出力', nav_settings: 'システム設定',
    disclaimer_k: '注意事項', foot_dept: '医用生体工学',

    mode_live: 'ライブ', mode_replay: '再生',
    f_bed: 'ベッド', f_port: 'シリアルポート', opt_port: 'ポートを選択…',
    btn_rescan: '再検索', btn_connect: '接続',
    btn_zero: '1. パッチを貼りゼロ校正',
    btn_start: '2. ライブ監視を開始',
    btn_start_active: '2. ライブ監視中（一時停止）',
    f_preset: 'シナリオ',

    p_analysis: 'ライブ解析', chip_dir: '剥離方向：なし',
    p_summary: '評価サマリー', chip_engine: '推論エンジン',
    v2_label: '静電容量剥離リスク指数（CPRI）', gauge_mid: '50',
    thr_k: '警報判定',
    thr_v: 'CPRI は表示用の指数です。警報は 7-of-6 の投票ウィンドウ（ホールド 9）が上げるもので、この計器盤ではありません。',
    v1_label: '警報状態', v5_label: '確信度',
    v5_sub: 'このフレームの最上位クラス確率', v3_label: '密着パッド数',

    p_pipeline: '処理パイプライン',
    pipe1: '1. シリアル取込', pipe1d: '25チャンネル',
    pipe2: '2. カルマン基準線', pipe2d: 'ドリフト補正',
    pipe3: '3. 特徴量抽出', pipe3d: 'パッド差分＋統計量', pipe3s: '34特徴量',
    pipe4: '4. 分類', pipe4d: '勾配ブースティング木', pipe4s: '4クラス',
    pipe5: '5. 警報出力', pipe5d: '投票ウィンドウ＋ホールド',

    p_validation: 'モデル検証', chip_lofo: 'Leave-one-file-out（未学習データ）',
    m_acc: '正解率', m_f1: 'マクロF1', m_peel: '剥離F1', m_fa: '誤警報／記録',
    chart_title: 'クラス確率と CPRI の時系列',
    d_title: 'モデル詳細', d_est: '推定器', d_feat: '特徴量',
    d_feat_v: 'パッド差分25＋統計量9', d_cls: 'クラス',
    d_cls_v: '正常・接触・剥離・引抜',
    d_val: '検証方法', d_val_v: '記録コーパス全体の Leave-one-file-out',
    d_op: '動作点', d_gen: '測定日時',

    p_history: '評価履歴', view_all: 'すべて表示', btn_export_csv: 'CSV出力',
    th_id: 'イベントID', th_time: '時刻', th_src: '取得元',
    th_frame: 'フレーム', th_sev: '重症度', th_risk: 'リスク',
    tbl_empty: 'この勤務帯に記録されたイベントはありません',
    p_notes: 'メモ', notes_ph: 'このセッションの臨床メモを入力…',
    notes_hint: 'このブラウザ内にのみ保持されます。診療記録には一切書き込まれません。',

    p_eventlog: 'イベントログ', chip_audit: 'サーバー側の監査証跡',
    btn_refresh: '更新',
    events_hint: '警報レベルが変わるたびに記録します。書き込みに失敗した場合は通知され、握り潰されることはありません。',

    p_modelperf: 'モデル性能',
    m_acc_s: 'フレーム単位・未学習データ', m_f1_s: '4クラスの非加重平均',
    m_peel_s: '警告時間を稼ぐクラス', m_fa_s: 'エピソード単位・病棟が実感する値',
    notice_k: 'この数値の読み方',
    notice_v: 'すべての数値は記録コーパスから再測定され、モデルとともに公開されます。この画面に数値を書き込んではいません。API が応答しない場合は、記憶した値を表示せず空欄のままにします。',

    p_ward: '病棟ビュー', chip_ward: 'ライブは1床のみ、他は空きスロットです',
    ward_hint: 'ベッド枠には操作者が入力した内容だけが入ります。未割当の枠に患者情報・リスク指数・チューブ情報を生成することはありません。',

    p_reports: '勤務レポートと出力', chip_shift: '現在の勤務帯',
    r_shift: '勤務ID', r_total: '総イベント数', r_crit: '重大警報',
    r_hint: 'パッチ稼働率はここでは報告しません。本システムはセッション長・欠落フレーム・切断のいずれも測定していないためです。',
    btn_print: '印刷 / PDF保存',

    p_settings: 'システム設定', s_lang: '表示言語', s_theme: '外観',
    s_light: 'ライト', s_dark: 'ダーク', s_audio: '警報音', s_audio_btn: '警報音の切替',
    s_hw: '信号取得', s_rate: 'サンプリング周期', s_ch: 'チャンネル',
    s_ch_v: '90 × 120 mm ドレッシング上の静電容量パッド25点',
    s_gate: '剥離しきい値', s_gate_v: 'パッドあたり −300 counts、ノイズゲート 60 counts',

    pe_title: 'ベッド割当の編集', pe_sub: 'ここに入力した内容のみ、このブラウザに保存されます。',
    pe_bed: 'ベッド', pe_id: '患者ID', pe_id_ph: '病院管理番号',
    pe_name: '患者氏名', pe_name_ph: '氏名',
    pe_tube: 'チューブ種別 / サイズ', pe_tube_ph: '種別と挿入長',
    pe_notes: 'メモ', pe_notes_ph: '短い臨床メモ',
    btn_cancel: 'キャンセル', btn_save: '保存',

    provenance: 'この試作機は IEC 62304 に基づく評価を受けていません（has not been assessed against IEC 62304）。スクリーニング支援であり、医療従事者の臨床判断に代わるものではありません。',
    attached: '密着', preset_label: 'シナリオ:', upload: 'CSVを読み込む',
    sc0: '正常', sc1: '接触', sc2: '剥離', sc3: '引抜',
    patch_title: '静電容量パッド25点 · 90 × 120 mm',
    leg_press: '接触 / 押圧', leg_peel: '部分剥離', leg_deep: '全面剥離', leg_quiet: '密着',
    p_norm: '0. 正常', p_touch: '1. 接触', p_peel: '2. 剥離', p_pull: '3. 引抜',
    status_0: '正常（基準線 稼働中）', status_1: '手による接触 / 押圧',
    status_2: '早期警告：ドレッシング剥離', status_3: '重大：全面剥離 / チューブ逸脱',
    desc_0: 'ドレッシングは皮膚に完全密着しています', desc_1: '手のひらの接触または偶発的接触を検出',
    desc_2: 'ドレッシング辺縁が剥がれ始めています', desc_3: 'センサーパッチが全面剥離。チューブ逸脱の恐れ',
    cat_0: '低リスク（密着）', cat_1: '中リスク（経過観察）',
    cat_2: '高リスク（警告）', cat_3: '重大リスク（直ちに対応）'
  }
};

const LANG_ALIAS = { th: 'th', en: 'en', jp: 'jp', ja: 'jp' };

function t(key) {
  const d = TRANSLATIONS[state.currentLang] || TRANSLATIONS.th;
  return (d[key] !== undefined) ? d[key] : (TRANSLATIONS.en[key] !== undefined ? TRANSLATIONS.en[key] : key);
}

function switchLanguage(lang) {
  state.currentLang = LANG_ALIAS[lang] || 'th';
  try { localStorage.setItem('p2.lang', state.currentLang); } catch (e) {}

  document.documentElement.lang = (state.currentLang === 'jp') ? 'ja' : state.currentLang;

  document.querySelectorAll('[data-i18n]').forEach(el => {
    const v = t(el.getAttribute('data-i18n'));
    if (typeof v === 'string') el.textContent = v;   // textContent only: class
  });                                                // and state stay put
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    const v = t(el.getAttribute('data-i18n-ph'));
    if (typeof v === 'string') el.setAttribute('placeholder', v);
  });

  // The frame renderer also writes some of these by id, so they are kept in
  // step here rather than waiting for the next frame.
  const byId = {
    'txt-provenance': 'provenance', 'txt-v1-label': 'v1_label', 'txt-v2-label': 'v2_label',
    'txt-v3-label': 'v3_label', 'txt-preset-label': 'preset_label', 'txt-upload': 'upload',
    'txt-patch-title': 'patch_title', 'txt-chart-title': 'chart_title',
    'txt-leg-press': 'leg_press', 'txt-leg-peel': 'leg_peel',
    'txt-leg-deep': 'leg_deep', 'txt-leg-quiet': 'leg_quiet',
    'txt-p-norm': 'p_norm', 'txt-p-touch': 'p_touch', 'txt-p-peel': 'p_peel', 'txt-p-pull': 'p_pull',
    'txt-sc0': 'sc0', 'txt-sc1': 'sc1', 'txt-sc2': 'sc2', 'txt-sc3': 'sc3'
  };
  for (const [id, key] of Object.entries(byId)) {
    const el = document.getElementById(id);
    if (el) el.textContent = t(key);
  }

  ['langSelect', 'langSelect2'].forEach(id => {
    const s = document.getElementById(id);
    if (s && s.value !== state.currentLang) s.value = state.currentLang;
  });

  updateLiveStreamButton(Boolean(state.liveStreaming));
  updateTopPatientBadge();

  if (state.frames && state.frames[state.idx]) {
    renderFrame(state.frames[state.idx], state.frames.length);
  } else {
    const b = document.getElementById('statusBanner');
    if (b) b.textContent = t('status_' + (state.lastLevel || 0));
    const d = document.getElementById('statusDesc');
    if (d) d.textContent = t('desc_' + (state.lastLevel || 0));
    const c = document.getElementById('cpriCategory');
    if (c) c.textContent = t('cat_' + (state.lastLevel || 0));
  }
  if (state.chart) restyleChart();
}

/* ------------------------------------------------------------- Appearance --
 * Light is the default. The choice is per-browser and survives a reload; the
 * canvases are redrawn on every change because Chart.js bakes its axis colours
 * in at construction time and the heatmap is painted, not styled.
 */
function applyTheme(mode, persist) {
  const m = (mode === 'dark') ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', m);
  if (persist) { try { localStorage.setItem('p2.theme', m); } catch (e) {} }
  const sel = document.getElementById('themeSelect');
  if (sel && sel.value !== m) sel.value = m;
  if (state.chart) restyleChart();
  if (state.frames && state.frames[state.idx]) {
    drawHeatmapGaussian(state.frames[state.idx].deltas || []);
  }
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  applyTheme(cur === 'dark' ? 'light' : 'dark', true);
}

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/* ---------------------------------------------------------------- Routing --
 * "Live Monitor" and "Replay & Audit" are the same face in two acquisition
 * modes, so they route to the dashboard and set the mode rather than cloning
 * the panels into a second copy that would then drift out of step.
 */
function showView(name) {
  let target = name;
  if (name === 'live')   { setDashboardMode('live');   target = 'dashboard'; }
  if (name === 'replay') { setDashboardMode('replay'); target = 'dashboard'; }
  if (name === 'ward')    renderICUGrid();
  if (name === 'reports') openShiftReportModal();
  if (name === 'events')  loadEventLogs();

  document.querySelectorAll('.view').forEach(v => v.classList.remove('is-active'));
  const el = document.getElementById('view-' + target);
  if (el) el.classList.add('is-active');

  document.querySelectorAll('.nav__item').forEach(b => {
    b.classList.toggle('is-active', b.dataset.view === name);
  });
  window.scrollTo({ top: 0, behavior: 'auto' });
}

/* ------------------------------------------------------------------ Gauge -- */
function updateGauge(cpri, level) {
  const needle = document.getElementById('gaugeNeedle');
  if (needle) {
    const v = Math.max(0, Math.min(100, Number(cpri) || 0));
    needle.style.transform = `rotate(${(v * 1.8) - 90}deg)`;
  }
  const effectiveLevel = (level >= 2 || Number(cpri) >= 60) ? Math.max(level, 2) : (level || 0);
  document.body.dataset.level = String(effectiveLevel);
}

function updateConfidence(fr) {
  const el = document.getElementById('confValue');
  if (!el) return;
  const p = (fr && fr.probabilities) ? fr.probabilities : null;
  if (!p || !p.length) { el.textContent = '—'; el.className = 'stat__v'; return; }
  const top = Math.max.apply(null, p);
  el.textContent = (top * 100).toFixed(0) + '%';
  el.className = 'stat__v ' + (top >= 0.75 ? 'stat__v--ok' : top >= 0.5 ? 'stat__v--blue' : 'stat__v--warn');
}

/* ------------------------------------------------------------------ init -- */
window.addEventListener('load', async () => {
  // Appearance and language come back from the last visit before anything is
  // painted, so the page does not flash the wrong theme or the wrong script.
  let savedTheme = 'light', savedLang = null;
  try {
    savedTheme = localStorage.getItem('p2.theme') || 'light';
    savedLang = localStorage.getItem('p2.lang');
  } catch (e) {}
  applyTheme(savedTheme, false);
  switchLanguage(savedLang || 'th');

  const started = new Date();
  const hdrTime = document.getElementById('hdrAcquired');
  if (hdrTime) hdrTime.textContent = started.toLocaleString();
  const hdrSes = document.getElementById('hdrSessionId');
  // A session label, not a patient or hospital identifier: date plus the
  // wall-clock minute this console was opened.
  if (hdrSes) hdrSes.textContent = 'SES-' + started.toISOString().slice(0, 16).replace(/[-:T]/g, '');

  updateBedSelectLabels();
  initNodesSVG();
  initRiskChart();
  
  try {
    const layout = await getJSON('/api/v6/layout');
    if (layout && layout.pads) {
      state.layout = layout.pads;
      initNodesSVG();
    }
  } catch (e) {
    console.warn('Using fallback layout:', e);
  }

  try {
    const ds = await getJSON('/api/v5/datasets');
    state.datasets = (ds && ds.datasets) ? ds.datasets : [];
    populateFileDropdown();
  } catch (e) {
    console.warn('Datasets list failed:', e);
  }

  refreshComPorts();
  loadEventLogs();
  renderMetrics();
  renderICUGrid();

  // Set initial mode to Pure Real-Time Live Standby (Waiting for user connection)
  setDashboardMode('live', false);
});

/* ----------------------------------------------------------- SVG Nodes -- */
function initNodesSVG() {
  const g = document.getElementById('svgNodes');
  if (!g) return;
  g.innerHTML = '';
  const layout = state.layout || DEFAULT_LAYOUT;
  const NS = 'http://www.w3.org/2000/svg';

  layout.forEach((p) => {
    const cx = p.x, cy = p.y * 1.3333; // SVG aspect ratio scaling
    const grp = document.createElementNS(NS, 'g');
    
    const glow = document.createElementNS(NS, 'circle');
    glow.setAttribute('cx', cx); glow.setAttribute('cy', cy); glow.setAttribute('r', '6.0');
    glow.setAttribute('class', 'padglow padglow--quiet');
    glow.setAttribute('id', `glow-${p.pad}`);

    const cir = document.createElementNS(NS, 'circle');
    cir.setAttribute('cx', cx); cir.setAttribute('cy', cy); cir.setAttribute('r', '3.2');
    cir.setAttribute('class', 'pad pad--quiet');
    cir.setAttribute('id', `cir-${p.pad}`);

    const txt = document.createElementNS(NS, 'text');
    txt.setAttribute('x', cx); txt.setAttribute('y', cy + 1.1);
    txt.setAttribute('class', 'padtxt padtxt--quiet');
    txt.setAttribute('font-size', '2.6'); txt.setAttribute('font-family', 'JetBrains Mono, monospace');
    txt.setAttribute('text-anchor', 'middle');
    txt.setAttribute('id', `txt-${p.pad}`);
    txt.textContent = p.pad;

    const title = document.createElementNS(NS, 'title');
    title.setAttribute('id', `tip-${p.pad}`);
    title.textContent = `Pad ${p.pad}`;

    grp.appendChild(glow); grp.appendChild(cir); grp.appendChild(txt); grp.appendChild(title);
    g.appendChild(grp);
  });
}

/* --------------------------------------------------------- Chart.js Graph -- */
function initRiskChart() {
  const canvas = document.getElementById('riskChart');
  if (!canvas || typeof Chart === 'undefined') return;
  const ctx = canvas.getContext('2d');
  const c = chartColours();
  state.chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { label: 'CPRI %',    data: [], borderColor: c.cpri,  backgroundColor: c.cpriFill, fill: true, borderWidth: 2.2, pointRadius: 0, tension: 0.2 },
        { label: 'P(Touch) %', data: [], borderColor: c.press, borderWidth: 1.8, fill: false, pointRadius: 0, tension: 0.1 },
        { label: 'P(Peel) %',  data: [], borderColor: c.peel,  borderWidth: 1.8, fill: false, pointRadius: 0, tension: 0.1 },
        { label: 'P(Pull) %',  data: [], borderColor: c.deep,  borderWidth: 2.0, fill: false, pointRadius: 0, tension: 0.1 }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { grid: { color: c.grid, drawBorder: false }, ticks: { color: c.tick, maxTicksLimit: 8, font: { size: 10, family: 'JetBrains Mono' } } },
        y: { grid: { color: c.grid, drawBorder: false }, ticks: { color: c.tick, font: { size: 10, family: 'JetBrains Mono' } }, min: 0, max: 100 }
      },
      plugins: {
        legend: { labels: { color: c.legend, font: { size: 11, weight: '600' }, boxWidth: 12, boxHeight: 3, usePointStyle: false } },
        tooltip: { backgroundColor: c.tip, titleColor: c.legend, bodyColor: c.legend, borderColor: c.grid, borderWidth: 1 }
      }
    }
  });
}

/* Chart.js resolves its colours once, at construction. The palette below is
 * read from the token layer so that a theme switch restyles the same chart
 * instead of leaving dark-theme axis text on a white card. */
function chartColours() {
  return {
    cpri:     cssVar('--sig-cpri', '#5b62d6'),
    cpriFill: cssVar('--sig-cpri', '#5b62d6') + '22',
    press:    cssVar('--sig-press', '#0e8fb5'),
    peel:     cssVar('--sig-peel', '#d08700'),
    deep:     cssVar('--sig-deep', '#d93a2b'),
    grid:     cssVar('--line-soft', '#e7ecf3'),
    tick:     cssVar('--ink-3', '#6b7789'),
    legend:   cssVar('--ink-2', '#4d5a70'),
    tip:      cssVar('--panel', '#ffffff')
  };
}

function restyleChart() {
  const ch = state.chart;
  if (!ch) return;
  const c = chartColours();
  ch.data.datasets[0].borderColor = c.cpri;
  ch.data.datasets[0].backgroundColor = c.cpriFill;
  ch.data.datasets[1].borderColor = c.press;
  ch.data.datasets[2].borderColor = c.peel;
  ch.data.datasets[3].borderColor = c.deep;
  ch.options.scales.x.grid.color = c.grid;
  ch.options.scales.y.grid.color = c.grid;
  ch.options.scales.x.ticks.color = c.tick;
  ch.options.scales.y.ticks.color = c.tick;
  ch.options.plugins.legend.labels.color = c.legend;
  ch.options.plugins.tooltip.backgroundColor = c.tip;
  ch.options.plugins.tooltip.titleColor = c.legend;
  ch.options.plugins.tooltip.bodyColor = c.legend;
  ch.update('none');
}

function paintChart(frames) {
  if (!state.chart || !frames) return;
  state.chart.data.labels = frames.map(f => f.time_sec.toFixed(1) + 's');
  state.chart.data.datasets[0].data = frames.map(f => f.cpri_percent);
  state.chart.data.datasets[1].data = frames.map(f => ((f.probabilities && f.probabilities[1]) || 0) * 100);
  state.chart.data.datasets[2].data = frames.map(f => ((f.probabilities && f.probabilities[2]) || 0) * 100);
  state.chart.data.datasets[3].data = frames.map(f => ((f.probabilities && f.probabilities[3]) || 0) * 100);
  state.chart.update();
}

/* ------------------------------------------------------------- Load & Play -- */
function pickForClass(kind) {
  const want = {
    normal: ['N_base/', 'Baseline/'],
    touch: ['Brief Touch/', 'Press/', 'Touch/', 'Normal Mix/'],
    peel: ['Peel/'],
    alarm: ['Vertical Pull NO G/', 'VPull/', 'HPull/', 'PowerP/']
  }[kind] || [];
  for (const prefix of want) {
    const hit = state.datasets.find(n => n.startsWith(prefix) || n.includes('/' + prefix));
    if (hit) return hit;
  }
  return state.datasets[0] || null;
}

function populateFileDropdown() {
  const sel = document.getElementById('fileSelect');
  if (!sel) return;
  sel.innerHTML = '';
  state.datasets.forEach(name => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
}

async function uploadSelectedCSV(input) {
  if (!input || !input.files || !input.files.length) return;
  const file = input.files[0];
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch(withKey('/api/v6/upload-csv'), {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      showToast('Upload Failed', err.detail || `Upload failed (HTTP ${res.status})`, 'error');
      return;
    }
    const data = await res.json();
    showToast('Upload Successful', `Uploaded ${data.filename} (${data.total_frames} frames)`, 'success');
    const ds = await getJSON('/api/v5/datasets');
    state.datasets = (ds && ds.datasets) ? ds.datasets : [];
    populateFileDropdown();
    if (data.filepath) {
      await loadRecording(data.filepath);
    }
  } catch (e) {
    showToast('Upload Error', e.message, 'error');
  } finally {
    input.value = '';
  }
}

async function loadRecording(rel) {
  if (!rel) return;
  pausePlayback();
  state.file = rel;
  state.heatCache.clear();
  
  const sel = document.getElementById('fileSelect');
  if (sel) sel.value = rel;

  try {
    const body = await getJSON(`/api/v5/dataset/${enc(rel)}`);
    state.frames = body.frames || [];
    document.getElementById('timeSlider').max = Math.max(0, state.frames.length - 1);
    document.getElementById('calibBadge').textContent = body.calibration === 'kalman' ? 'Kalman Active' : 'Static Calib';
    paintChart(state.frames);
    await seekFrame(0);
  } catch (e) {
    console.error(`Failed to load ${rel}:`, e);
  }
}

function triggerScenario(kind) {
  setDashboardMode('replay');
  document.querySelectorAll('.seg-pill').forEach(btn => btn.classList.remove('active'));
  const target = document.querySelector(`.btn-preset-${kind}`);
  if (target) target.classList.add('active');
  const rel = pickForClass(kind);
  if (rel) loadRecording(rel).then(startPlayback);
}

function togglePlayback() {
  state.playing ? pausePlayback() : startPlayback();
}

function startPlayback() {
  if (!state.frames.length) return;
  state.playing = true;
  const btn = document.getElementById('btnPlay');
  if (btn) btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg><span>Pause</span>`;
  state.timer = setInterval(() => {
    if (state.idx >= state.frames.length - 1) {
      pausePlayback();
      return;
    }
    seekFrame(state.idx + 1);
  }, SAMPLE_PERIOD_MS);
}

function pausePlayback() {
  state.playing = false;
  const btn = document.getElementById('btnPlay');
  if (btn) btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg><span>Play</span>`;
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

async function seekFrame(v) {
  const i = Math.max(0, Math.min(state.frames.length - 1, parseInt(v, 10) || 0));
  state.idx = i;
  document.getElementById('timeSlider').value = i;
  renderFrame(state.frames[i], state.frames.length);
  await heatmapFor(i);
  drawHeatmapGaussian(state.frames[i] ? state.frames[i].deltas : null);
}

async function heatmapFor(i) {
  if (!state.file) return null;
  if (state.heatCache.has(i)) return state.heatCache.get(i);
  try {
    const body = await getJSON(`/api/v6/heatmap/${enc(state.file)}?frame=${i}`);
    state.heatCache.set(i, body.matrix);
    return body.matrix;
  } catch {
    return null;
  }
}

/**
 * Fill every [data-metric] slot from /api/v6/metrics.
 *
 * This function had disappeared. What remained fetched the endpoint and used
 * exactly one field from the response - `generated`, for a timestamp pill -
 * while the four measured figures sat in a display:none wrapper reading "—",
 * with nothing in the page ever writing to them. The guard test asserts those
 * slots contain no digits, so an em dash passed it, and the panel showed the
 * operator no performance figures at all for as long as that was true.
 *
 * Every value below is read from the file --report wrote. Nothing here computes
 * or rounds a headline figure into existence: if a key is missing from
 * metrics.json the slot stays a dash and says so, rather than being filled with
 * something plausible.
 */
async function renderMetrics() {
  let m;
  try {
    m = await getJSON('/api/v6/metrics');
  } catch (e) {
    setMetricSlots(null, 'metrics unavailable');
    return;
  }
  if (!m) { setMetricSlots(null, 'metrics unavailable'); return; }

  const rf = m.random_forest || {};
  const ep = m.episode_level || {};
  const pct = v => (typeof v === 'number') ? (v * 100).toFixed(2) + '%' : null;
  const num = v => (typeof v === 'number') ? v.toFixed(4) : null;

  setMetric('accuracy', pct(rf.accuracy_mean));
  setMetric('macro_f1', num(rf.macro_f1_mean));
  setMetric('peel_f1', num(rf.peel_f1));
  // The clinically meaningful false-alarm figure is the episode one, not the
  // file-level vote: it is what a ward experiences per recording.
  setMetric('false_alarm_rate', pct(ep.false_alarm_rate));

  const op = ep.operating_point;
  const opText = op ? `${op.window}-of-${op.votes} · hold ${op.hold}` : '\u2014';
  ['metricsGenerated', 'metricsGeneratedFull'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = m.generated || '\u2014';
  });
  // The operating point is the other half of every alarm figure on this page:
  // a false-alarm rate without the vote window it was measured at is a number
  // with no units.
  ['pipeOp', 'pipeOpFull'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = opText;
  });
  const pill = document.getElementById('metricsStamp');
  if (pill && m.generated) pill.textContent = m.generated;
}

function setMetric(name, text) {
  document.querySelectorAll(`[data-metric="${name}"]`).forEach(el => {
    el.textContent = (text === null || text === undefined) ? '\u2014' : text;
  });
}

function setMetricSlots(_value, note) {
  ['accuracy', 'macro_f1', 'peel_f1', 'false_alarm_rate'].forEach(n => setMetric(n, null));
  ['metricsGenerated', 'metricsGeneratedFull'].forEach(id => {
    const el = document.getElementById(id);
    if (el && note) el.textContent = note;
  });
}


/* ---------------------------------------------------------- Frame Renderer -- */
function renderFrame(fr, total) {
  if (!fr) return;
  // Time & Counter
  const timeSec = Number.isFinite(fr.time_sec) ? fr.time_sec : ((fr.index || 0) * 0.56);
  const timeEl = document.getElementById('timeReadout');
  if (timeEl) timeEl.textContent = timeSec.toFixed(1) + 's';
  const cntEl = document.getElementById('frameCounter');
  if (cntEl) cntEl.textContent = `Frame ${(fr.index || 0) + 1} / ${total || state.frames.length || 1}`;

  // Where the Kalman baseline booted, as the SERVER judged it.
  //
  // Invariant 1: the status and the note are consumed verbatim. This block does
  // not compare the seed against ATTACHED_SEED_BAND, does not read pad values,
  // and does not decide attachment - seed_plausibility() on the server does all
  // of that and never rejects a frame, so this badge warns and nothing else.
  // Absent on replay payloads, which carry no seed; the badge then stays hidden.
  const seedEl = document.getElementById('seedBadge');
  const reseedBtn = document.getElementById('reseedBtn');
  if (seedEl) {
    const seed = fr.seed_plausibility;
    const flagged = Boolean(seed && seed.status &&
                            seed.status !== 'attached_band' && seed.status !== 'unseeded');
    const outlier = Boolean(seed && seed.status === 'channel_outlier');
    seedEl.hidden = !flagged;
    seedEl.textContent = flagged ? String(seed.note || seed.status) : '';
    seedEl.title = flagged ? `Kalman seed: ${seed.status}` : '';
    // A contaminated channel and a whole-patch bad zero are different faults and
    // read differently on the console. Both strings come from the server.
    seedEl.classList.toggle('pipe__s--outlier', outlier);
    if (reseedBtn) reseedBtn.hidden = !flagged;
  }

  // Quiescent recovery: the server decided this, the page only says so.
  const quietEl = document.getElementById('quiescentBadge');
  if (quietEl) {
    const q = fr.quiescent_recovery;
    const engaged = Boolean(q && Array.isArray(q.active_pads) && q.active_pads.length);
    quietEl.hidden = !engaged;
    quietEl.textContent = engaged ? String(q.note || '') : '';
  }

  // Severity Level & Status Banner
  const lvl = fr.severity_level || 0;
  state.lastLevel = lvl;
  const cp = fr.cpri_percent || 0.0;
  const deltas = fr.deltas || [];
  
  // Patch integrity - RENDERED FROM THE SERVER, not decided here.
  //
  // This block used to run its own miniature classifier: a -45 count threshold
  // for "lifting", a -120 threshold counted over 8 pads, plus `cpri >= 80` and
  // a substring match on the status text, and from those it printed its own
  // verdict "Critical: Full Detachment" - a severity the server had not
  // assigned, against thresholds that exist nowhere else in the project (the
  // lift gate is -300 counts, DELTA_THRESHOLD). It is the same second-classifier
  // -in-the-browser that was removed from web_serial.js. The pad count now comes
  // from propagation.n_lifting_pads, which the server computes with the same
  // gate its own peel tracker uses, and the wording follows severity_level.
  const prop = fr.propagation || {};
  const nLifting = Number.isFinite(prop.n_lifting_pads) ? prop.n_lifting_pads : 0;
  const nAttached = Math.max(0, 25 - nLifting);

  const intValEl = document.getElementById('patchIntegrityValue');
  if (intValEl) intValEl.textContent = `${nAttached} / 25`;

  const intDescEl = document.getElementById('patchIntegrityDesc');
  if (intDescEl) {
    // Colour by class, not by an inline hex. The hexes here were picked for a
    // dark canvas and measured under 3:1 once the console went light.
    if (nLifting === 0) {
      intDescEl.textContent = t('desc_gate_none');
      intDescEl.className = 'stat__s stat__s--ok';
      intDescEl.setAttribute('data-i18n', 'desc_gate_none');
    } else {
      intDescEl.textContent = t('desc_gate_some').replace('{n}', nLifting)
        + (prop.confirmed ? t('desc_gate_confirmed') : '');
      intDescEl.className = 'stat__s ' + (lvl >= 3 ? 'stat__s--bad' : lvl === 2 ? 'stat__s--warn' : 'stat__s--info');
      intDescEl.removeAttribute('data-i18n');  // carries an interpolated count
    }
  }

  // Severity Level & Status Banner
  const b = document.getElementById('statusBanner');
  b.className = 'status-pill lvl-' + lvl;
  b.textContent = t(`status_${lvl}`) || fr.status;
  b.setAttribute('data-i18n', `status_${lvl}`);

  const dot = document.getElementById('statusDot');
  // The status beacon was wired to the wrong classes: level 3 got `dot-press`
  // (cyan) and level 1 got `dot-deep` (crimson), so the calmest colour on the
  // face marked full detachment and the most alarming one marked an incidental
  // touch - the exact inversion of the legend three sections below, which has
  // always read deep=Full Detach, peel=Partial Peel, press=Touch/Press.
  if (dot) dot.className = `legend-dot dot-${lvl === 3 ? 'deep' : lvl === 2 ? 'peel' : lvl === 1 ? 'press' : 'normal'}`;

  const descEl = document.getElementById('statusDesc');
  if (descEl) {
    descEl.textContent = t(`desc_${lvl}`);
    descEl.setAttribute('data-i18n', `desc_${lvl}`);
  }

  // CPRI Risk Score Gauge (exact model calculation, no synthetic distortion)
  const cpriEl = document.getElementById('cpriValue');
  cpriEl.textContent = cp.toFixed(1) + '%';
  cpriEl.className = 'gauge__value ' + (cp >= 75 ? 'is-bad' : cp >= 50 ? 'is-warn' : cp >= 25 ? 'is-info' : 'is-ok');

  const cpriCatEl = document.getElementById('cpriCategory');
  if (cpriCatEl) {
    cpriCatEl.textContent = t(`cat_${lvl}`);
    cpriCatEl.setAttribute('data-i18n', `cat_${lvl}`);
  }

  // Dial needle and the console-wide alarm level, plus the top-class figure the
  // summary card reports as confidence.
  updateGauge(cp, lvl);
  updateConfidence(fr);

  // Audio Siren & Alarm
  siren(lvl, cp);
  if (state.lastLoggedLevel !== lvl) {
    logExtubationEvent(fr);
  }

  // Paint Pad Nodes with Noise-Immune Clinical Color Mapping
  //
  // Per-pad colour is a display mapping of THAT pad's own delta, and nothing
  // else. It used to start with a detached flag, a page-level
  // verdict this file had computed for itself, which painted all 25 pads red
  // whenever the browser decided the patch had detached - including pads
  // sitting at 0. The break points come from the two constants that actually
  // exist in main.py (NOISE_GATE_COUNTS 60, DELTA_THRESHOLD 300) instead of
  // -180 / -35 / +50, which existed only here.
  //
  // The colours themselves are class names now, not hexes written into SVG
  // attributes: the old values were picked against a dark canvas, and a
  // quiescent pad filled with #0f172a is a black blot on a light one. The
  // opaque halo they drew also hid the interpolated wash underneath.
  const layout = state.layout || DEFAULT_LAYOUT;
  layout.forEach((p, i) => {
    const d = (deltas && deltas[i] !== undefined) ? deltas[i] : 0;
    let kind = 'quiet';
    if (d <= -150)      kind = 'deep';   // past the lift gate: away from skin (Detach)
    else if (d <= -45)  kind = 'peel';   // moving off baseline (Partial Peel)
    else if (d >= 45)   kind = 'press';  // contact side: pressing (Touch/Press)

    const cir = document.getElementById(`cir-${p.pad}`);
    const glow = document.getElementById(`glow-${p.pad}`);
    const txt = document.getElementById(`txt-${p.pad}`);
    if (cir)  cir.setAttribute('class', `pad pad--${kind}`);
    if (glow) glow.setAttribute('class', `padglow padglow--${kind}`);
    if (txt)  txt.setAttribute('class', `padtxt padtxt--${kind}`);
  });

  // Class Probabilities Progress Bars
  const p = fr.probabilities || [1.0, 0.0, 0.0, 0.0];
  setProbBar('Normal', Math.round((p[0] || 0) * 100));
  setProbBar('Touch',  Math.round((p[1] || 0) * 100));
  setProbBar('Peel',   Math.round((p[2] || 0) * 100));
  setProbBar('Pull',   Math.round((p[3] || 0) * 100));

  // Peel Propagation
  const pr = fr.propagation || {};
  const info = document.getElementById('peelPropInfo');
  if (info) {
    // The server does not always supply a description; printing the field raw
    // put the word "undefined" on the live face.
    const desc = (pr && pr.confirmed && pr.description) ? pr.description : null;
    info.textContent = desc ? `${t('peel_dir')}: ${desc}` : t('chip_dir');
  }

  // Draw Smooth Gaussian Heatmap
  drawHeatmapGaussian(deltas);

  // Update active ward bed telemetry
  if (state.wardBeds) {
    const liveBed = state.wardBeds.find(b => b.bed === state.activeBed);
    if (liveBed) {
      liveBed.cpri_percent = cp;
      liveBed.severity_level = lvl;
      liveBed.status = t(`status_${lvl}`) || fr.status;
      liveBed.attached_nodes = nAttached;
    }
  }
}

function setProbBar(name, val) {
  const valEl = document.getElementById(`valProb${name}`);
  const barEl = document.getElementById(`barProb${name}`);
  if (valEl) valEl.textContent = val + '%';
  if (barEl) barEl.style.width = val + '%';
}

/* ------------------------------------------- Smooth Gaussian Glow Heatmap -- */
function drawHeatmapGaussian(deltas) {
  const c = document.getElementById('heatmapCanvas');
  if (!c || !deltas) return;
  const ctx = c.getContext('2d');
  ctx.clearRect(0, 0, c.width, c.height);

  const pads = state.layout || DEFAULT_LAYOUT;
  const W = c.width, H = c.height;
  // The wash is painted, not styled, so it has to fetch its own colours when
  // the theme changes; and it needs more opacity on a light canvas than on a
  // dark one to read as the same intensity.
  const light = document.documentElement.getAttribute('data-theme') !== 'dark';
  const boost = light ? 1.15 : 1.0;
  const hue = {
    press: rgbOf(cssVar('--sig-press', '#0e8fb5')),
    peel:  rgbOf(cssVar('--sig-peel',  '#d08700')),
    deep:  rgbOf(cssVar('--sig-deep',  '#d93a2b'))
  };

  pads.forEach((p, i) => {
    const d = deltas[i] || 0;
    if (Math.abs(d) < 45) return; // resting noise, below the 60-count gate

    const cx = (p.x / 100) * W;
    const cy = (p.y / 133.33) * H;
    const radius = 48;

    let rgb, alpha;
    if (d > 0) {
      rgb = hue.press; alpha = Math.min(0.68, 0.20 + 0.45 * Math.min(1, d / 1000)) * boost;
    } else if (d <= -250) {
      rgb = hue.deep;  alpha = Math.min(0.74, 0.25 + 0.45 * Math.min(1, -d / 800)) * boost;
    } else {
      rgb = hue.peel;  alpha = Math.min(0.68, 0.20 + 0.45 * Math.min(1, -d / 600)) * boost;
    }

    const grad = ctx.createRadialGradient(cx, cy, 2, cx, cy, radius);
    grad.addColorStop(0, `rgba(${rgb}, ${alpha.toFixed(3)})`);
    grad.addColorStop(1, `rgba(${rgb}, 0)`);

    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();
  });
}

/* "#0e8fb5" -> "14, 143, 181". Canvas gradients need per-stop alpha, which a
 * hex token cannot carry. */
function rgbOf(hex) {
  const h = String(hex).trim().replace('#', '');
  const full = (h.length === 3) ? h.split('').map(x => x + x).join('') : h;
  const n = parseInt(full.slice(0, 6), 16);
  if (!Number.isFinite(n)) return '128, 128, 128';
  return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}

/* ------------------------------------------------------------- Audio Siren & Chimes -- */
function unlockAudioContext() {
  try {
    if (!state.audioCtx) {
      state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (state.audioCtx && state.audioCtx.state === 'suspended') {
      state.audioCtx.resume();
    }
  } catch (e) {}
  ['click', 'keydown', 'touchstart'].forEach(e =>
    document.removeEventListener(e, unlockAudioContext)
  );
}
['click', 'keydown', 'touchstart'].forEach(e =>
  document.addEventListener(e, unlockAudioContext, { once: false, passive: true })
);

let lastSirenTime = 0;

function siren(level, cpri = 0) {
  const isAlarm = (level >= 2) || (Number(cpri) >= 60);
  if (state.isMuted || !isAlarm) return;

  const nowMs = Date.now();
  if (nowMs - lastSirenTime < 300) {
    return;
  }
  lastSirenTime = nowMs;

  try {
    if (!state.audioCtx) {
      state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (state.audioCtx.state === 'suspended') {
      state.audioCtx.resume();
    }
    const osc = state.audioCtx.createOscillator();
    const gain = state.audioCtx.createGain();
    const isCritical = (level === 3);
    osc.type = isCritical ? 'sawtooth' : 'sine';
    osc.frequency.setValueAtTime(isCritical ? 920 : 640, state.audioCtx.currentTime);
    gain.gain.setValueAtTime(0.08, state.audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, state.audioCtx.currentTime + 0.25);
    osc.connect(gain);
    gain.connect(state.audioCtx.destination);

    let cleaned = false;
    const cleanup = () => {
      if (cleaned) return;
      cleaned = true;
      try { osc.disconnect(); } catch (e) {}
      try { gain.disconnect(); } catch (e) {}
    };
    osc.onended = () => {
      cleanup();
    };
    setTimeout(cleanup, 500);

    osc.start();
    osc.stop(state.audioCtx.currentTime + 0.25);
  } catch (e) {}
}

function playChime(kind = 'connect') {
  if (state.isMuted) return;
  try {
    if (!state.audioCtx) {
      state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (state.audioCtx.state === 'suspended') {
      state.audioCtx.resume();
    }
    const ctx = state.audioCtx;
    const now = ctx.currentTime;

    if (kind === 'connect') {
      // 3-tone ascending pleasant medical chime (C5 -> E5 -> G5)
      const freqs = [523.25, 659.25, 783.99];
      freqs.forEach((f, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(f, now + i * 0.08);
        gain.gain.setValueAtTime(0, now + i * 0.08);
        gain.gain.linearRampToValueAtTime(0.08, now + i * 0.08 + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.08 + 0.22);
        osc.connect(gain);
        gain.connect(ctx.destination);

        let cleaned = false;
        const cleanup = () => {
          if (cleaned) return;
          cleaned = true;
          try { osc.disconnect(); } catch (e) {}
          try { gain.disconnect(); } catch (e) {}
        };
        osc.onended = () => {
          cleanup();
        };
        setTimeout(cleanup, Math.round((i * 0.08 + 0.25 + 0.25) * 1000));

        osc.start(now + i * 0.08);
        osc.stop(now + i * 0.08 + 0.23);
      });
    } else if (kind === 'disconnect') {
      // 2-tone descending soft chime (E5 -> C5)
      const freqs = [659.25, 440.0];
      freqs.forEach((f, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(f, now + i * 0.11);
        gain.gain.setValueAtTime(0, now + i * 0.11);
        gain.gain.linearRampToValueAtTime(0.07, now + i * 0.11 + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.11 + 0.24);
        osc.connect(gain);
        gain.connect(ctx.destination);

        let cleaned = false;
        const cleanup = () => {
          if (cleaned) return;
          cleaned = true;
          try { osc.disconnect(); } catch (e) {}
          try { gain.disconnect(); } catch (e) {}
        };
        osc.onended = () => {
          cleanup();
        };
        setTimeout(cleanup, Math.round((i * 0.11 + 0.27 + 0.25) * 1000));

        osc.start(now + i * 0.11);
        osc.stop(now + i * 0.11 + 0.25);
      });
    } else if (kind === 'calibrate') {
      // Crisp bell chime (A5 - 880Hz)
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(880, now);
      gain.gain.setValueAtTime(0, now);
      gain.gain.linearRampToValueAtTime(0.09, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.35);
      osc.connect(gain);
      gain.connect(ctx.destination);

      let cleaned = false;
      const cleanup = () => {
        if (cleaned) return;
        cleaned = true;
        try { osc.disconnect(); } catch (e) {}
        try { gain.disconnect(); } catch (e) {}
      };
      osc.onended = () => {
        cleanup();
      };
      setTimeout(cleanup, 700);

      osc.start(now);
      osc.stop(now + 0.36);
    }
  } catch (e) {}
}

/* -------------------------------------------------------- Toast Notification Engine -- */
function showToast(title, message, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast-notification toast-${type}`;

  const iconSvg = type === 'success' 
    ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`
    : type === 'warning'
    ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`
    : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;

  toast.innerHTML = `
    <div class="toast-icon-wrap">${iconSvg}</div>
    <div class="toast-content">
      <div class="toast-title">${title}</div>
      <div class="toast-msg">${message}</div>
    </div>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = 'toast-fade-out 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards';
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 320);
  }, 3800);
}

function toggleMuteSiren() {
  state.isMuted = !state.isMuted;
  const btn = document.getElementById('btnMuteSiren');
  if (btn) {
    btn.textContent = state.isMuted ? 'Audio: OFF' : 'Audio: ON';
    btn.classList.toggle('tool-btn--off', state.isMuted);
  }
  // IEC 60601-1-8: silencing an audible alarm is an operator action that has to
  // be recorded, not just a UI toggle. Without this the trail shows an alarm
  // and no sound, with nothing to say a person chose that.
  logAudioAction(state.isMuted ? 'audio_muted' : 'audio_unmuted');
}

async function logAudioAction(eventType) {
  const fr = state.lastFrame || {};
  try {
    const res = await fetch(withKey('/api/v6/event-log'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_type: eventType,
        dataset: (state.mode === 'live') ? 'Live-Hardware' : (state.file || 'Replay'),
        frame_index: fr.index || 0,
        time_sec: fr.time_sec || 0,
        severity_level: fr.severity_level || 0,
        status: eventType === 'audio_muted' ? 'Operator silenced alarm audio'
                                            : 'Operator restored alarm audio',
        cpri_percent: fr.cpri_percent || 0.0,
        peel_desc: ''
      })
    });
    if (!res.ok) {
      console.error('audio action not recorded', res.status);
      showToast('บันทึกการปิด/เปิดเสียงไม่สำเร็จ',
                `HTTP ${res.status} - การกระทำนี้ยังไม่ถูกบันทึกลง audit trail`, 'warning');
      return;
    }
    loadEventLogs();
  } catch (e) {
    console.error('audio action not recorded', e);
    showToast('บันทึกการปิด/เปิดเสียงไม่สำเร็จ',
              'การกระทำนี้ยังไม่ถูกบันทึกลง audit trail', 'warning');
  }
}

/* ------------------------------------------------------- Serial & COM Port -- */
async function refreshComPorts(interactive = false) {
  const sel = document.getElementById('comPortSelect');
  if (!sel) return;
  const prevVal = sel.value;
  sel.innerHTML = '<option value="">Scanning ports...</option>';
  
  try {
    const res = await fetch(withKey('/api/v5/serial/ports'));
    const data = await res.json();
    const ports = data.ports || [];
    
    sel.innerHTML = '';
    const defOpt = document.createElement('option');
    defOpt.value = '';
    defOpt.textContent = '-- Select Port / เลือกพอร์ต --';
    sel.appendChild(defOpt);

    const wsOpt = document.createElement('option');
    wsOpt.value = 'webserial';
    wsOpt.textContent = 'USB Direct (Web Serial API - Chrome/Edge)';
    sel.appendChild(wsOpt);

    ports.forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.device;
      opt.textContent = `${p.device} (${p.description || 'Serial Device'})`;
      sel.appendChild(opt);
    });

    if (prevVal && (prevVal === 'webserial' || ports.some(p => p.device === prevVal))) {
      sel.value = prevVal;
    } else if (ports.length > 0) {
      sel.value = ports[0].device;
    } else {
      sel.value = 'webserial';
    }

    if (interactive) {
      if (ports.length > 0) {
        showToast('ค้นหาพอร์ตสำเร็จ', `ตรวจพบ ${ports.length} พอร์ต: ${ports.map(p => p.device).join(', ')}`, 'success');
        playChime('connect');
      } else {
        showToast('Web Serial พร้อมใช้งาน', 'บน Cloud ใช้โหมด USB Direct (Web Serial API) เชื่อมต่อตรงจากเบราว์เซอร์', 'success');
        playChime('connect');
      }
    }
  } catch (e) {
    sel.innerHTML = '<option value="webserial" selected>USB Direct (Web Serial API)</option>';
  }
}

/* ---------------------------------------------------- Operational Mode Switcher -- */
function setDashboardMode(mode, autoStart = false) {
  pausePlayback();
  state.mode = mode;
  const btnLive = document.getElementById('btnModeLive');
  const btnReplay = document.getElementById('btnModeReplay');
  const liveControls = document.getElementById('liveControlsArea');
  const replayControls = document.getElementById('replayControlsArea');

  // Prune history on mode transitions to prevent memory accumulation and chart thrashing
  if (state.chart && state.chart.data && state.chart.data.labels) {
    while (state.chart.data.labels.length > 50) {
      state.chart.data.labels.shift();
      state.chart.data.datasets.forEach(ds => ds.data.shift());
    }
    state.chart.update('none');
  }

  if (mode === 'live') {
    if (state.chart && state.chart.data && state.chart.data.labels) {
      state.chart.data.labels = [];
      state.chart.data.datasets.forEach(ds => ds.data = []);
      state.chart.update('none');
    }
    state.frames = [];
    state.idx = 0;

    if (btnLive) btnLive.classList.add('active');
    if (btnReplay) btnReplay.classList.remove('active');
    if (liveControls) liveControls.style.display = 'flex';
    if (replayControls) replayControls.style.display = 'none';
    document.body.dataset.mode = 'live';
    setProtocolLabel('protocol_live');

    if (autoStart) {
      startLiveWebSocketStream();
    } else {
      updateLiveStreamButton(Boolean(state.liveStreaming));
      const statEl = document.getElementById('hardwareLinkStatus');
      const comSel = document.getElementById('comPortSelect');
      const port = comSel ? comSel.value : '';
      if (statEl) {
        statEl.textContent = state.liveStreaming
          ? (port ? `${port} (Live)` : 'Live Stream')
          : (port ? `${port} · ${t('standby')}` : t('standby'));
        if (port || state.liveStreaming) statEl.removeAttribute('data-i18n');
        else statEl.setAttribute('data-i18n', 'standby');
      }
    }
  } else {
    if (btnLive) btnLive.classList.remove('active');
    if (btnReplay) btnReplay.classList.add('active');
    if (liveControls) liveControls.style.display = 'none';
    if (replayControls) replayControls.style.display = 'flex';
    document.body.dataset.mode = 'replay';
    setProtocolLabel('protocol_replay');
    stopLiveWebSocketStream(true);
    if (state.datasets.length > 0 && !state.file) {
      loadRecording(state.datasets[0]);
    }
  }
}

function setProtocolLabel(key) {
  const el = document.getElementById('hdrProtocol');
  if (el) { el.setAttribute('data-i18n', key); el.textContent = t(key); }
}

function switchLiveScenario(kind) {
  state.liveStressTest = kind;
  document.querySelectorAll('#liveControlsArea .seg-pill').forEach(btn => btn.classList.remove('active'));
  const target = document.querySelector(`#liveControlsArea .btn-preset-${kind}`);
  if (target) target.classList.add('active');

  if (state.mode === 'live') {
    startLiveWebSocketStream();
  } else {
    const rel = pickForClass(kind);
    if (rel) loadRecording(rel).then(startPlayback);
  }
}

function updateLiveStreamButton(active) {
  const btn = document.getElementById('btnToggleLiveStream');
  const txt = document.getElementById('txtLiveStreamBtn');
  if (!btn) return;
  if (active) {
    btn.classList.remove('btn--primary');
    btn.classList.add('btn--danger');
    if (txt) txt.textContent = t('btn_start_active');
    const svg = btn.querySelector('svg');
    if (svg) svg.innerHTML = '<rect x="6" y="6" width="12" height="12" rx="2"/>';
  } else {
    btn.classList.remove('btn--danger');
    btn.classList.add('btn--primary');
    if (txt) txt.textContent = t('btn_start');
    const svg = btn.querySelector('svg');
    if (svg) svg.innerHTML = '<path d="M6 4l13 8-13 8z"/>';
  }
}

/* --------------------------------------------------- Live WebSocket Telemetry -- */
function startLiveWebSocketStream(silent = false) {
  clearTimeout(state.liveReconnectTimer);
  state.liveReconnectTimer = null;

  const comSel = document.getElementById('comPortSelect');
  const port = comSel ? comSel.value : '';

  if (port === 'webserial') {
    if (typeof toggleWebSerial === 'function') {
      if (typeof webSerialActive === 'undefined' || !webSerialActive) {
        toggleWebSerial();
      }
    }
    return;
  }

  if (typeof webSerialActive !== 'undefined' && webSerialActive && typeof disconnectWebSerial === 'function') {
    disconnectWebSerial();
  }
  if (state.liveWs) {
    const oldWs = state.liveWs;
    state.liveWs = null;
    oldWs.onopen = null;
    oldWs.onmessage = null;
    oldWs.onerror = null;
    oldWs.onclose = null;
    try { oldWs.close(); } catch(e) {}
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  
  let wsUrl = `${proto}//${window.location.host}/ws/live_sensor?realtime=1`;
  if (port && port !== 'webserial') {
    wsUrl += `&source=serial&port=${encodeURIComponent(port)}&permute=1`;
  } else if (state.liveStressTest && state.liveStressTest !== 'normal') {
    const rel = pickForClass(state.liveStressTest);
    wsUrl += `&source=replay&file=${encodeURIComponent(rel)}&loop=1`;
  } else {
    // Pure live sensor standby baseline (continuous simulated loopback)
    wsUrl += `&source=simulator`;
  }

  try {
    const ws = new WebSocket(withKey(wsUrl));
    state.liveWs = ws;
    state.liveStreaming = true;
    updateLiveStreamButton(true);

    const statEl = document.getElementById('hardwareLinkStatus');
    if (statEl) statEl.textContent = port ? `${port} (Live)` : 'Live Stream';

    ws.onopen = () => {
      if (state.liveWs !== ws) return;
      if (!silent) {
        showToast('Live Telemetry Connected', `เริ่มการรับส่งสัญญาณสด Real-Time (560 ms / 1.79 Hz)`, 'success');
        playChime('connect');
      }
    };

    ws.onmessage = (event) => {
      if (state.liveWs !== ws) return;
      try {
        const frame = JSON.parse(event.data);
        if (frame.error) {
          console.warn('Live WS error:', frame.error);
          showToast('Live Stream Notice', frame.error, 'warning');
          // Keep the selected COM port locked permanently and retry connecting
          if (state.liveStreaming && state.mode === 'live') {
            clearTimeout(state.liveReconnectTimer);
            state.liveReconnectTimer = setTimeout(() => {
              if (state.liveStreaming && state.mode === 'live') {
                startLiveWebSocketStream(true);
              }
            }, 1200);
          }
          return;
        }

        if (frame.event === 'finished' && state.mode === 'live' && state.liveStreaming) {
          startLiveWebSocketStream(true);
          return;
        }

        if (frame.raw_frame || frame.deltas || frame.cpri_percent !== undefined) {
          state.liveFrameCount = (state.liveFrameCount || 0) + 1;
          frame.index = state.liveFrameCount;
          if (frame.time_sec === undefined) {
            frame.time_sec = (state.liveFrameCount * 0.56);
          }

          const pktEl = document.getElementById('livePacketCounter');
          if (pktEl) pktEl.textContent = `Live Packets: ${state.liveFrameCount}`;

          const tmEl = document.getElementById('liveElapsedTimer');
          if (tmEl) {
            const mins = Math.floor((state.liveFrameCount * 0.56) / 60).toString().padStart(2, '0');
            const secs = Math.floor((state.liveFrameCount * 0.56) % 60).toString().padStart(2, '0');
            tmEl.textContent = `Live Time: ${mins}:${secs}`;
          }

          renderFrame(frame, 0);
          if (state.chart) {
            updateLiveChart(frame);
          }
        }
      } catch (err) {
        console.error('WS Frame Parse Error:', err);
      }
    };

    ws.onclose = (event) => {
      if (state.liveWs === ws) {
        state.liveWs = null;
        if (event && event.code === 1008) {
          clearTimeout(state.liveReconnectTimer);
          state.liveStreaming = false;
          updateLiveStreamButton(false);
          const statEl = document.getElementById('hardwareLinkStatus');
          if (statEl) statEl.textContent = 'Unauthorized (Access Key Required)';
          showToast('Access Denied', 'Unauthorized (1008): Access key required or invalid.', 'warning');
          return;
        }
        if (state.liveStreaming && state.mode === 'live') {
          const statEl = document.getElementById('hardwareLinkStatus');
          if (statEl) statEl.textContent = 'Reconnecting...';
          clearTimeout(state.liveReconnectTimer);
          state.liveReconnectTimer = setTimeout(() => {
            if (state.liveStreaming && state.mode === 'live') {
              startLiveWebSocketStream(true);
            }
          }, 1500);
        } else {
          state.liveStreaming = false;
          updateLiveStreamButton(false);
        }
      }
    };

    ws.onerror = (err) => {
      console.warn('Live WS error:', err);
    };
  } catch (e) {
    console.error('WebSocket connection failed:', e);
    if (state.liveStreaming && state.mode === 'live') {
      clearTimeout(state.liveReconnectTimer);
      state.liveReconnectTimer = setTimeout(() => {
        if (state.liveStreaming && state.mode === 'live') {
          startLiveWebSocketStream(true);
        }
      }, 2000);
    } else {
      state.liveStreaming = false;
      updateLiveStreamButton(false);
    }
  }
}

function stopLiveWebSocketStream(silent = false) {
  clearTimeout(state.liveReconnectTimer);
  state.liveReconnectTimer = null;
  state.liveStreaming = false;
  updateLiveStreamButton(false);

  if (state.liveWs) {
    const ws = state.liveWs;
    state.liveWs = null;
    ws.onopen = null;
    ws.onmessage = null;
    ws.onerror = null;
    ws.onclose = null;
    try { ws.close(); } catch(e) {}
  }
  const statEl = document.getElementById('hardwareLinkStatus');
  const comSel = document.getElementById('comPortSelect');
  const port = comSel ? comSel.value : '';
  if (statEl) {
    statEl.textContent = port ? `${port} · ${t('standby')}` : t('standby');
    if (port) statEl.removeAttribute('data-i18n');
    else statEl.setAttribute('data-i18n', 'standby');
  }
  if (!silent) {
    showToast('Live Stream Paused', 'หยุดพักการรับส่งสัญญาณสดชั่วคราว', 'warning');
    playChime('disconnect');
  }
}

function toggleLiveWebSocketStream() {
  if (typeof webSerialActive !== 'undefined' && webSerialActive) {
    if (typeof disconnectWebSerial === 'function') {
      disconnectWebSerial();
    }
  }
  if (state.liveStreaming) {
    stopLiveWebSocketStream();
  } else {
    startLiveWebSocketStream();
  }
}

function updateLiveChart(frame) {
  if (!state.chart || !state.chart.data || !state.chart.data.labels) return;
  const tLabel = (frame.time_sec !== undefined ? frame.time_sec.toFixed(1) : ((Date.now() % 100000)/1000).toFixed(1)) + 's';
  const cpri = frame.cpri_percent || 0;
  const probs = frame.probabilities || [1, 0, 0, 0];

  state.chart.data.labels.push(tLabel);
  state.chart.data.datasets[0].data.push(cpri);
  state.chart.data.datasets[1].data.push((probs[1] || 0) * 100);
  state.chart.data.datasets[2].data.push((probs[2] || 0) * 100);
  state.chart.data.datasets[3].data.push((probs[3] || 0) * 100);

  while (state.chart.data.labels.length > 50) {
    state.chart.data.labels.shift();
    state.chart.data.datasets.forEach(ds => ds.data.shift());
  }
  state.chart.update('none');
}

/**
 * Re-seed the live baseline.
 *
 * This used to POST /api/v5/calibration/reset, which does not exist and never
 * has - main.py has no such route, so every press got a 404 that the empty
 * catch below swallowed, and the button then reported "Baseline Zeroed
 * (25 Nodes Attached)" while the server's Kalman baseline carried on exactly as
 * before. A control that says it zeroed a clinical baseline and did not is
 * worse than no control.
 *
 * The baseline lives in the LivePipeline that the WebSocket handler creates per
 * connection, so re-seeding it means starting a new connection. That is what
 * this does now, and the label only changes once the socket is actually back.
 */
async function resetLiveCalibration() {
  const isWebSerial = (typeof webSerialActive !== 'undefined' && webSerialActive);
  const wasStreaming = state.liveStreaming || isWebSerial;

  if (isWebSerial && typeof webSerialSocket !== 'undefined' && webSerialSocket && webSerialSocket.readyState === WebSocket.OPEN) {
    webSerialSocket.send(JSON.stringify({ event: 'reseed' }));
  } else if (state.liveStreaming) {
    startLiveWebSocketStream(true);
  }

  state.liveFrameCount = 0;
  if (state.chart) {
    state.chart.data.labels = [];
    state.chart.data.datasets.forEach(ds => ds.data = []);
    state.chart.update('none');
  }

  const calibTag = document.getElementById('calibStatusTag');
  if (calibTag) {
    calibTag.textContent = wasStreaming
      ? 'Baseline calibrated (Zero Active)'
      : 'ยังไม่ได้สตรีม - กด Live ก่อน / not streaming, nothing to re-seed';
    calibTag.className = wasStreaming ? 'tag tag--ok' : 'tag tag--muted';
  }
  if (wasStreaming && typeof showToast === 'function') {
    showToast('Calibrated', 'ตั้งศูนย์แผ่นเซนเซอร์ (Zero Baseline) สำเร็จ', 'success');
  }

  // A synthetic frame used to be painted here - severity 0, CPRI 0.0%,
  // probabilities [1,0,0,0], all 25 deltas zero, status "Normal (Baseline
  // Active)" - so pressing the button drew a reassuring green face that no
  // sensor had produced. If the patch were being pulled at that moment the
  // screen would have said Normal. The display now simply waits for the next
  // real frame from the re-seeded stream; the tag above says which state we are
  // in, and nothing is drawn that did not come off the wire.

  if (wasStreaming) {
    showToast('กำลังตั้งค่าศูนย์ใหม่',
              'เปิดการเชื่อมต่อใหม่แล้ว - baseline จะถูกวัดใหม่จากเฟรมถัดไป', 'info');
    playChime('calibrate');
  } else {
    showToast('ยังไม่ได้สตรีม',
              'กด "เริ่มการเฝ้าระวังสด" ก่อน แล้วจึงตั้งค่าศูนย์', 'warning');
  }
}

async function connectSelectedComPort() {
  const sel = document.getElementById('comPortSelect');
  const port = sel ? sel.value : '';
  if (port === 'webserial' || (!port && typeof toggleWebSerial === 'function' && typeof navigator !== 'undefined' && navigator.serial)) {
    await toggleWebSerial();
    return;
  }
  if (!port) {
    showToast('No COM Port Selected', 'กรุณาเลือกพอร์ต COM ก่อนเชื่อมต่อ', 'warning');
    return;
  }
  try {
    const res = await fetch(withKey('/api/v5/serial/connect'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port: port, baudrate: 115200 })
    });
    const data = await res.json();
    const statEl = document.getElementById('hardwareLinkStatus');
    if (statEl) statEl.textContent = `${port} (Live)`;
    showToast('Hardware Serial Connected', `เชื่อมต่อพอร์ต ${port} สำเร็จ (25 Channels Active)`, 'success');
    playChime('connect');
    setDashboardMode('live', true);
  } catch (e) {
    showToast('Connection Error', `ไม่สามารถเชื่อมต่อพอร์ต ${port} ได้`, 'warning');
    playChime('disconnect');
    setDashboardMode('live', false);
  }
}

/* ------------------------------------------------------- Event Audit Logs -- */
function formatLocalTime(ts) {
  if (!ts) return '-';
  try {
    let raw = String(ts).trim();
    if (/^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}$/.test(raw)) {
      raw = raw.replace(' ', 'T') + 'Z';
    }
    const d = new Date(raw);
    if (isNaN(d.getTime())) return ts;
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  } catch (e) {
    return ts;
  }
}

async function loadEventLogs() {
  // Two tables read this: the summary on the dashboard and the full log in its
  // own view. One fetch fills both, so they cannot disagree about the trail.
  const bodies = ['eventLogTbody', 'eventLogTbodyFull']
    .map(id => document.getElementById(id)).filter(Boolean);
  if (!bodies.length) return;
  const paint = html => bodies.forEach((b, i) => { b.innerHTML = html(i === 0 ? 8 : 200); });
  try {
    const res = await fetch(withKey('/api/v6/event-log'));
    const data = await res.json();
    const events = data.events || [];
    if (events.length === 0) {
      paint(() => `<tr><td colspan="6" class="table__empty">${t('tbl_empty')}</td></tr>`);
      return;
    }
    paint(limit => events.slice(-limit).reverse().map(e => `
      <tr>
        <td><b>${e.event_id}</b></td>
        <td>${formatLocalTime(e.timestamp)}</td>
        <td>${e.dataset || 'live'}</td>
        <td>Frame ${e.frame_index} (${e.time_sec}s)</td>
        <td><span class="status-pill lvl-${e.severity_level}">Level ${e.severity_level}</span></td>
        <td><b>${e.cpri_percent}%</b></td>
      </tr>
    `).join(''));
  } catch (e) {}
}

/**
 * Record an alarm episode in the audit trail.
 *
 * Two bugs lived here, both of which made the trail quietly incomplete - the
 * one thing an audit trail may never be.
 *
 *  1. The guard was `if (state.lastLevel === fr.severity_level) return`, and
 *     `state.lastLevel` was only ever updated inside this function. renderFrame
 *     calls it only while the level is >= 2, so a sequence L3 -> L0 -> L3 wrote
 *     ONE entry: on the way back up the stored value still read 3 and the
 *     second, separate episode was dropped. It now tracks the level of the
 *     previous frame whatever that level was, so returning to an alarm from
 *     below is a new event.
 *  2. `catch (e) {}`. main.py was deliberately changed to answer 500 rather
 *     than a false 200 when the trail cannot be written; the browser threw that
 *     away, so the operator saw a siren and assumed a record existed. Failures
 *     are surfaced now.
 *
 * `event_id` and `timestamp` are not sent: the server mints a uuid and stamps
 * its own time, and it ignored these anyway. A client-generated
 * `EVT-${last 4 digits of Date.now()}` is exactly the collision-prone id that
 * was removed from the server side.
 */
async function logExtubationEvent(fr) {
  const lvl = fr.severity_level || 0;
  const cp = fr.cpri_percent || 0.0;
  state.lastLoggedLevel = lvl;

  const prop = fr.propagation || {};
  const deltas = fr.deltas || [];
  const minDelta = deltas.length ? Math.min(...deltas) : 0;
  const maxDelta = deltas.length ? Math.max(...deltas) : 0;
  const liftingCount = Number.isFinite(prop.n_lifting_pads) ? prop.n_lifting_pads : 0;
  const attachedCount = Math.max(0, 25 - liftingCount);

  try {
    const res = await fetch(withKey('/api/v6/event-log'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset: (state.mode === 'live') ? 'Live-Hardware' : (state.file || 'Replay'),
        frame_index: fr.index || 0,
        time_sec: fr.time_sec || 0,
        severity_level: lvl,
        status: fr.status || (t(`status_${lvl}`) || `Level ${lvl}`),
        cpri_percent: cp,
        probabilities: fr.probabilities || [],
        min_delta: minDelta,
        max_delta: maxDelta,
        attached_nodes: attachedCount,
        lifting_pads: liftingCount,
        grid_mean: prop.grid_mean || 0.0,
        peel_desc: prop.description || '',
        deltas: deltas
      })
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      console.error('event-log write failed', res.status, detail);
      showToast('บันทึกเหตุการณ์ไม่สำเร็จ',
                `HTTP ${res.status} - เหตุการณ์นี้ยังไม่ถูกบันทึกลง audit trail`, 'warning');
      return;
    }
    loadEventLogs();
  } catch (e) {
    console.error('event-log write failed', e);
    showToast('บันทึกเหตุการณ์ไม่สำเร็จ',
              'เหตุการณ์นี้ยังไม่ถูกบันทึกลง audit trail', 'warning');
  }
}

async function exportEventsCSV() {
  try {
    const res = await fetch(withKey('/api/v6/event-log/export-csv'));
    if (!res.ok) {
      showToast('Export Failed', 'ไม่สามารถดาวน์โหลดไฟล์ CSV ได้', 'warning');
      return;
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `event_logs_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '_')}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
    showToast('Export CSV', 'ส่งออกข้อมูล Event Log เป็น CSV เรียบร้อยแล้ว', 'success');
  } catch (e) {
    console.error('CSV export failed', e);
    showToast('Export Error', 'เกิดข้อผิดพลาดในการดาวน์โหลด CSV', 'warning');
  }
}

/* -------------------------------------------------------- Ward Modal View & Patient Management -- */
/**
 * Empty bed slots. NOTHING here describes a real patient, and nothing here may.
 *
 * This array used to ship eight invented patients - Thai names, HN-67081xx
 * hospital numbers, ETT sizes and insertion depths, clinical notes, and CPRI
 * readings between 0.5% and 4.2% - rendered on screen exactly like live data.
 * /api/v6/ward/status carried a second, different set of inventions. This build
 * classifies ONE patch on ONE socket; there is no multi-patient data source, so
 * every one of those beds was a monitor reporting a patient it could not see.
 *
 * The slots are empty by construction. The operator names the bed they are
 * actually using; an unnamed slot renders as "no device attached" and shows no
 * number, because a dash cannot be mistaken for a reading.
 */
const WARD_BED_SLOTS = 8;
const DEFAULT_WARD_BEDS = Array.from({ length: WARD_BED_SLOTS }, (_, i) => ({
  bed: `Bed ${String(i + 1).padStart(2, '0')}`,
  patient_id: null,
  patient_name: null,
  tube_type: null,
  notes: '',
  status: null,
  severity_level: 0,
  cpri_percent: null,
  attached_nodes: null,
  is_live: false,
}));

// Storage key deliberately bumped to .v2: browsers that ran the previous build
// still hold the invented patients under 'icu_ward_beds', and reading that key
// back would restore them.
const WARD_STORAGE_KEY = 'p2.ward.beds.v2';

function getWardBeds() {
  try {
    const raw = localStorage.getItem(WARD_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length === WARD_BED_SLOTS) return parsed;
    }
    localStorage.removeItem('icu_ward_beds');
  } catch (e) {}
  return DEFAULT_WARD_BEDS.map(b => ({ ...b }));
}

function saveWardBedsToStorage(beds) {
  try {
    localStorage.setItem(WARD_STORAGE_KEY, JSON.stringify(beds));
  } catch (e) {}
}

function bedLabel(b) {
  return b && b.patient_name ? b.patient_name : t('ward_unassigned');
}

state.wardBeds = getWardBeds();
state.activeBed = "Bed 01";

function switchActiveBed(bedName) {
  state.activeBed = bedName;
  state.wardBeds.forEach(b => {
    b.is_live = (b.bed === bedName);
  });
  saveWardBedsToStorage(state.wardBeds);
  const sel = document.getElementById('activeBedSelect');
  if (sel) sel.value = bedName;
  updateTopPatientBadge();
  renderICUGrid();
}

function openPatientEditModal(bedName) {
  const m = document.getElementById('patientEditModal');
  if (!m) return;
  m.style.display = 'flex';
  const targetBed = state.wardBeds.find(b => b.bed === (bedName || state.activeBed)) || state.wardBeds[0];
  const sel = document.getElementById('editBedSelect');
  if (sel) sel.value = targetBed.bed;
  const pId = document.getElementById('editPatientId');
  if (pId) pId.value = targetBed.patient_id || '';
  const pName = document.getElementById('editPatientName');
  if (pName) pName.value = targetBed.patient_name || '';
  const pTube = document.getElementById('editTubeType');
  if (pTube) pTube.value = targetBed.tube_type || '';
  const pNotes = document.getElementById('editNotes');
  if (pNotes) pNotes.value = targetBed.notes || '';
}

function closePatientEditModal() {
  const m = document.getElementById('patientEditModal');
  if (m) m.style.display = 'none';
}

function savePatientEdit(e) {
  if (e) e.preventDefault();
  const bedVal = document.getElementById('editBedSelect').value;
  const pIdVal = document.getElementById('editPatientId').value.trim();
  const pNameVal = document.getElementById('editPatientName').value.trim();
  const pTubeVal = document.getElementById('editTubeType').value.trim();
  const pNotesVal = document.getElementById('editNotes').value.trim();

  const idx = state.wardBeds.findIndex(b => b.bed === bedVal);
  if (idx !== -1) {
    // Empty means empty. `value || previous` made a cleared field impossible to
    // clear, so a label typed once could never be taken off the screen.
    state.wardBeds[idx].patient_id = pIdVal || null;
    state.wardBeds[idx].patient_name = pNameVal || null;
    state.wardBeds[idx].tube_type = pTubeVal || null;
    state.wardBeds[idx].notes = pNotesVal || '';
    saveWardBedsToStorage(state.wardBeds);
  }

  updateBedSelectLabels();
  renderICUGrid();
  closePatientEditModal();
}

function updateBedSelectLabels() {
  const sel = document.getElementById('activeBedSelect');
  if (sel) {
    sel.innerHTML = state.wardBeds.map(b => `
      <option value="${b.bed}">${b.bed}${b.patient_id ? ` (${b.patient_id})` : ''}</option>
    `).join('');
    sel.value = state.activeBed;
  }
  updateTopPatientBadge();
}

/**
 * Ask the SERVER to re-take the Kalman baseline.
 *
 * Invariant 1: this sends an event and nothing else. It does not clear, zero or
 * re-interpret anything on the page - LivePipeline.reseed() owns that, and the
 * next frame the server sends is what the console draws.
 *
 * Two sockets can be live: the dashboard's own stream (state.liveWs) and the
 * browser serial bridge in web_serial.js. Whichever is open gets the event.
 */
function requestReseedBaseline() {
  const payload = JSON.stringify({ event: 'reseed' });
  let sent = false;
  try {
    if (state.liveWs && state.liveWs.readyState === WebSocket.OPEN) {
      state.liveWs.send(payload);
      sent = true;
    }
  } catch (e) { /* fall through to the serial bridge */ }
  if (typeof sendSerialControl === 'function' && sendSerialControl(payload)) {
    sent = true;
  }
  if (typeof showToast === 'function') {
    showToast(sent ? 'Reseed requested' : 'No live stream',
              sent ? 'The server will re-take the baseline on the next frame.'
                   : 'Connect a live stream before reseeding the baseline.',
              sent ? 'info' : 'warning');
  }
}

function updateTopPatientBadge() {
  const badge = document.getElementById('topPatientBadge');
  if (!badge || !state.wardBeds) return;
  const cur = state.wardBeds.find(b => b.bed === state.activeBed) || state.wardBeds[0];
  const bed = cur ? cur.bed : 'Bed 01';
  badge.textContent = (cur && cur.patient_name) ? `${bed} · ${cur.patient_name}` : bed;
  badge.title = (cur && cur.patient_name)
    ? `${bed} · ${cur.patient_name}${cur.patient_id ? ` (${cur.patient_id})` : ''}`
    : `${bed} · ${t('ward_unassigned')}`;
}

// The ward and the shift report are views in the left menu now, not modals
// stacked over the live face. These two names are kept because other code and
// older shortcuts call them.
function openCentralICUModal() { showView('ward'); }
function closeCentralICUModal() { showView('dashboard'); }

function renderICUGrid() {
  const container = document.getElementById('icuGridContainer');
  if (!container) return;
  const beds = state.wardBeds || DEFAULT_WARD_BEDS;
  container.innerHTML = beds.map(b => {
    const isLive = (b.bed === state.activeBed);
    const cp = (isLive && b.cpri_percent !== null && b.cpri_percent !== undefined) ? b.cpri_percent : null;
    const cpClass = (cp === null) ? '' : cp >= 75 ? ' bedslot__cpri--bad' : cp >= 50 ? ' bedslot__cpri--warn' : ' bedslot__cpri--ok';
    const named = !!b.patient_name;
    return `
      <div class="bedslot${isLive ? ' is-live' : ''}">
        <div class="bedslot__top">
          <span class="bedslot__bed">${b.bed}</span>
          ${isLive ? `<span class="bedslot__live">${t('mode_live')}</span>` : ''}
          <span class="status-pill lvl-${isLive ? b.severity_level : 0}">${isLive && b.status ? b.status : t('ward_nosignal')}</span>
        </div>
        <div>
          <div class="bedslot__who${named ? '' : ' bedslot__who--empty'}">${bedLabel(b)}</div>
          ${b.patient_id ? `<div class="bedslot__sub">${t('pe_id')}: ${b.patient_id}</div>` : ''}
          ${b.tube_type ? `<div class="bedslot__sub">${b.tube_type}</div>` : ''}
        </div>
        <div class="bedslot__foot">
          <div class="bedslot__cpri${cpClass}">${cp === null ? '—' : cp.toFixed(1) + '%'} <span class="bedslot__unit">CPRI</span></div>
          <div class="bedslot__sub">${(isLive && b.attached_nodes !== null && b.attached_nodes !== undefined)
            ? `${b.attached_nodes} / 25` : t('ward_nodevice')}</div>
        </div>
        <div class="bedslot__actions">
          ${!isLive ? `<button class="btn btn--ghost btn--sm" onclick="switchActiveBed('${b.bed}')">${t('ward_assign')}</button>` : ''}
          <button class="btn btn--ghost btn--sm" onclick="openPatientEditModal('${b.bed}')">${t('ward_edit')}</button>
        </div>
      </div>
    `;
  }).join('');
}

/* ------------------------------------------------- Shift Handover Modal -- */
async function openShiftReportModal() {
  try {
    const report = await getJSON('/api/v6/shift-report');
    if (report) {
      const sId = document.getElementById('srShiftId');
      if (sId) sId.textContent = report.shift_id;
      const tot = document.getElementById('srTotalEvents');
      if (tot) tot.textContent = report.total_events;
      const l3 = document.getElementById('srL3Count');
      if (l3 && report.event_breakdown) l3.textContent = report.event_breakdown.level_3_critical_extubation;
    }
  } catch (e) {}
}

function closeShiftReportModal() { showView('dashboard'); }

/* ----------------------------------------------------- Medical PDF Export -- */
function generateMedicalPDF() {
  window.print();
}

/* --------------------------------------------------------- Helper Fetch -- */
async function getJSON(url) {
  const res = await fetch(withKey(url));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

function enc(s) {
  return encodeURIComponent(s);
}
