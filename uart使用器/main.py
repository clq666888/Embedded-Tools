import queue
import threading
import tkinter as tk
import sys
from collections import deque
from pathlib import Path
from tkinter import ttk

from frame_send import FrameSendMixin
from frame_parse import FrameParseMixin
from waveform import WaveformMixin
from serial_io import SerialMixin


class App(FrameSendMixin, FrameParseMixin, WaveformMixin, SerialMixin, tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UART 收发与数据帧解析")
        icon_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        icon_path = icon_root / "assets" / "uart.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass
        self.geometry("980x660")
        self.minsize(820, 560)
        self.port = None
        self.reader_thread = None
        self.q = queue.Queue()
        self.stop_reader = threading.Event()
        self.rx = bytearray()
        self.rx_chunks = []
        self._view_chunk_count=0
        self._view_chunk_lines=deque()
        self._serial_update_after=None
        self.app_dir=Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent
        self.build()
        self.refresh()
        self._port_refresh_after=self.after(350,self._auto_refresh_ports)
        self.after(50, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def build(self):
        self.configure(bg="#eef2f6")
        root = ttk.Frame(self, padding=(12, 10))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        nav = tk.Frame(root, bg="#ffffff", highlightthickness=1, highlightbackground="#dce3eb")
        nav.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        nav.columnconfigure(3, weight=1)
        self.nav_serial = tk.Button(nav, text="↔  串口收发", command=lambda: self.show_page("serial"),
                                   font=("Microsoft YaHei UI", 10), bd=0, padx=16, pady=10,
                                   bg="#e8f2fc", fg="#1769aa", activebackground="#d8eafa", cursor="hand2")
        self.nav_serial.grid(row=0, column=0, sticky="w", padx=(6, 3), pady=5)
        self.nav_parse = tk.Button(nav, text="▦  数据帧解析", command=lambda: self.show_page("parse"),
                                  font=("Microsoft YaHei UI", 10), bd=0, padx=16, pady=10,
                                  bg="#ffffff", fg="#425466", activebackground="#f0f4f8", cursor="hand2")
        self.nav_parse.grid(row=0, column=1, sticky="w", padx=3, pady=5)
        self.status = tk.StringVar(value="未连接")
        tk.Label(nav, textvariable=self.status, bg="#ffffff", fg="#607080",
                 font=("Microsoft YaHei UI", 9)).grid(row=0, column=4, sticky="e", padx=14)

        pages = ttk.Frame(root)
        pages.grid(row=1, column=0, sticky="nsew")
        pages.columnconfigure(0, weight=1)
        pages.rowconfigure(0, weight=1)
        self.pages = {}
        self.pages["serial"] = ttk.Frame(pages)
        self.pages["parse"] = ttk.Frame(pages)
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self.build_serial_page(self.pages["serial"])
        self.build_parse_page(self.pages["parse"])
        self.show_page("serial")

    def show_page(self, name):
        self.pages[name].tkraise()
        active = "#e8f2fc"
        normal = "#ffffff"
        self.nav_serial.configure(bg=active if name == "serial" else normal,
                                  fg="#1769aa" if name == "serial" else "#425466")
        self.nav_parse.configure(bg=active if name == "parse" else normal,
                                 fg="#1769aa" if name == "parse" else "#425466")

    def build_serial_page(self, page):
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        c=ttk.LabelFrame(page,text="串口设置",padding=9)
        c.grid(row=0,column=0,sticky="ew",pady=(0,8))
        ttk.Label(c,text="串口").grid(row=0,column=0)
        self.portname=tk.StringVar()
        self.port_map={}
        self.ports=ttk.Combobox(c,textvariable=self.portname,width=25,state="readonly",postcommand=self.refresh)
        self.ports.grid(row=0,column=1,sticky="ew",padx=5)
        self.ports.bind("<<ComboboxSelected>>",self._schedule_serial_reconfigure)
        self.conn=ttk.Button(c,text="连接",command=self.connect)
        self.conn.grid(row=0,column=2,padx=(0,10))
        ttk.Label(c,text="波特率").grid(row=0,column=3)
        self.baud=tk.StringVar(value="9600")
        self.baud_box=ttk.Combobox(c,textvariable=self.baud,values=("9600","19200","38400","57600","115200","230400","460800","921600"),width=10)
        self.baud_box.grid(row=0,column=4,padx=5)
        self.baud_box.bind("<<ComboboxSelected>>",self._schedule_serial_reconfigure)
        self.baud_box.bind("<Return>",self._schedule_serial_reconfigure)
        self.baud_box.bind("<FocusOut>",self._schedule_serial_reconfigure)
        ttk.Label(c,text="数据位").grid(row=0,column=5)
        self.bits=tk.StringVar(value="8")
        self.bits_box=ttk.Combobox(c,textvariable=self.bits,values=("5","6","7","8"),width=4,state="readonly")
        self.bits_box.grid(row=0,column=6,padx=5)
        self.bits_box.bind("<<ComboboxSelected>>",self._schedule_serial_reconfigure)
        ttk.Label(c,text="校验").grid(row=0,column=7)
        self.parity=tk.StringVar(value="None")
        self.parity_box=ttk.Combobox(c,textvariable=self.parity,values=("None","Even","Odd"),width=7,state="readonly")
        self.parity_box.grid(row=0,column=8,padx=5)
        self.parity_box.bind("<<ComboboxSelected>>",self._schedule_serial_reconfigure)
        ttk.Label(c,text="停止位").grid(row=0,column=9)
        self.stopbits=tk.StringVar(value="1")
        self.stopbits_box=ttk.Combobox(c,textvariable=self.stopbits,values=("1","1.5","2"),width=4,state="readonly")
        self.stopbits_box.grid(row=0,column=10,padx=5)
        self.stopbits_box.bind("<<ComboboxSelected>>",self._schedule_serial_reconfigure)
        panes=ttk.Panedwindow(page,orient="vertical")
        panes.grid(row=1,column=0,sticky="nsew")
        self.serial_panes=panes
        top=ttk.Frame(panes); bottom=ttk.Frame(panes)
        panes.add(top,weight=3); panes.add(bottom,weight=2)
        top.rowconfigure(0,weight=1); top.columnconfigure(0,weight=1)
        rf=ttk.LabelFrame(top,text="接收数据",padding=7)
        rf.grid(row=0,column=0,sticky="nsew")
        rf.rowconfigure(0,weight=1); rf.columnconfigure(0,weight=1)
        self.receive_views=ttk.Panedwindow(rf,orient="horizontal")
        self.receive_views.grid(row=0,column=0,columnspan=2,sticky="nsew")
        self.receive_views.columnconfigure(0,weight=1)
        self.hex_view=ttk.LabelFrame(self.receive_views,text="HEX",padding=4)
        self.text_view=ttk.LabelFrame(self.receive_views,text="文本",padding=4)
        self.out_hex=tk.Text(self.hex_view,font=("Consolas",11),wrap="word",state="disabled")
        self.out_hex.grid(row=0,column=0,sticky="nsew")
        self.out_hex.tag_configure("tx",foreground="#D74444")
        hex_sb=ttk.Scrollbar(self.hex_view,command=self.out_hex.yview)
        hex_sb.grid(row=0,column=1,sticky="ns")
        self.out_hex.configure(yscrollcommand=hex_sb.set)
        self.hex_view.rowconfigure(0,weight=1); self.hex_view.columnconfigure(0,weight=1)
        self.out_text=tk.Text(self.text_view,font=("Microsoft YaHei UI",10),wrap="word",state="disabled")
        self.out_text.grid(row=0,column=0,sticky="nsew")
        self.out_text.tag_configure("tx",foreground="#D74444")
        text_sb=ttk.Scrollbar(self.text_view,command=self.out_text.yview)
        text_sb.grid(row=0,column=1,sticky="ns")
        self.out_text.configure(yscrollcommand=text_sb.set)
        self.text_view.rowconfigure(0,weight=1); self.text_view.columnconfigure(0,weight=1)
        controls=ttk.Frame(rf)
        controls.grid(row=1,column=0,columnspan=2,sticky="ew",pady=(6,0))
        self.show_hex=tk.BooleanVar(value=True)
        self.show_text=tk.BooleanVar(value=False)
        ttk.Checkbutton(controls,text="HEX",variable=self.show_hex,
                        command=lambda:self._update_receive_layout("hex")).pack(side="left")
        ttk.Checkbutton(controls,text="文本",variable=self.show_text,
                        command=lambda:self._update_receive_layout("text")).pack(side="left",padx=6)
        ttk.Button(controls,text="清空记录",command=self.clear).pack(side="right")
        self._update_receive_layout()

        sf=ttk.LabelFrame(bottom,text="发送",padding=7)
        sf.pack(fill="both",expand=True)
        sf.columnconfigure(0,weight=1)
        sf.rowconfigure(0,weight=1)
        self.send_area=ttk.Frame(sf)
        self.send_area.grid(row=0,column=0,sticky="nsew")
        self.send_area.rowconfigure(0,weight=1); self.send_area.columnconfigure(0,weight=1)
        self.sendbox=tk.Text(self.send_area,height=4,font=("Consolas",10),wrap="word")
        self.sendbox.grid(row=0,column=0,sticky="nsew")
        self.frame_send_panel=ttk.Frame(self.send_area)
        self.frame_send_length=tk.StringVar(value="8")
        self.frame_send_endian=tk.StringVar(value="大端发送")
        self.frame_send_decimal_enabled=tk.BooleanVar(value=False)
        self._frame_send_fields=[{"value":"","positions":[]}]
        self._frame_send_manual_values=["00"]*8
        self._frame_send_hex_vars=[]
        self._frame_send_hex_entries=[]
        self._updating_frame_send_preview=False
        self._build_frame_send_editor(self.frame_send_panel)
        send_controls=ttk.Frame(sf)
        send_controls.grid(row=1,column=0,sticky="ew",pady=(6,0))
        self.sendmode=tk.StringVar(value="文本")
        ttk.Radiobutton(send_controls,text="文本发送",variable=self.sendmode,value="文本",
                        command=self._set_send_mode).pack(side="left")
        ttk.Radiobutton(send_controls,text="HEX发送",variable=self.sendmode,value="HEX",
                        command=self._set_send_mode).pack(side="left",padx=8)
        ttk.Radiobutton(send_controls,text="数据帧发送",variable=self.sendmode,value="数据帧",
                        command=self._set_send_mode).pack(side="left",padx=(8,0))
        self.crlf=tk.BooleanVar(value=False)
        self.crlf_check=ttk.Checkbutton(send_controls,text="追加换行 CRLF",variable=self.crlf)
        self.crlf_check.pack(side="left",padx=8)
        self.repeat_send=tk.BooleanVar(value=False)
        ttk.Button(send_controls,text="发送",command=self.send).pack(side="right")
        loop_controls=ttk.Frame(send_controls)
        loop_controls.pack(side="right",padx=(8,10))
        ttk.Checkbutton(loop_controls,text="循环发送",variable=self.repeat_send,
                        command=self._toggle_repeat_send).pack(side="left",padx=(0,4))
        ttk.Label(loop_controls,text="间隔").pack(side="left")
        self.repeat_interval=tk.StringVar(value="1.0")
        self.repeat_interval_box=ttk.Spinbox(loop_controls,from_=0.1,to=3600,increment=0.1,
            textvariable=self.repeat_interval,width=6)
        self.repeat_interval_box.pack(side="left",padx=(4,3))
        ttk.Label(loop_controls,text="秒").pack(side="left")
        self._send_after=None

        def set_initial_split():
            pane_height=panes.winfo_height()
            if pane_height>0:
                fraction=0.60
                panes.sashpos(0,int(pane_height*fraction))
        page.after(250,set_initial_split)


if __name__=="__main__":
    App().mainloop()
