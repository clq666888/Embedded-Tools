import json, queue, threading, tkinter as tk, sys
import time
import colorsys, re
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog, colorchooser
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


class App(tk.Tk):
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
        self.conn=ttk.Button(c,text="连接",command=self.connect)
        self.conn.grid(row=0,column=2,padx=(0,10))
        ttk.Label(c,text="波特率").grid(row=0,column=3)
        self.baud=tk.StringVar(value="9600")
        ttk.Combobox(c,textvariable=self.baud,values=("9600","19200","38400","57600","115200","230400","460800","921600"),width=10).grid(row=0,column=4,padx=5)
        ttk.Label(c,text="数据位").grid(row=0,column=5)
        self.bits=tk.StringVar(value="8")
        ttk.Combobox(c,textvariable=self.bits,values=("5","6","7","8"),width=4,state="readonly").grid(row=0,column=6,padx=5)
        ttk.Label(c,text="校验").grid(row=0,column=7)
        self.parity=tk.StringVar(value="None")
        ttk.Combobox(c,textvariable=self.parity,values=("None","Even","Odd"),width=7,state="readonly").grid(row=0,column=8,padx=5)
        ttk.Label(c,text="停止位").grid(row=0,column=9)
        self.stopbits=tk.StringVar(value="1")
        ttk.Combobox(c,textvariable=self.stopbits,values=("1","1.5","2"),width=4,state="readonly").grid(row=0,column=10,padx=5)
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
        ttk.Checkbutton(send_controls,text="追加换行 CRLF",variable=self.crlf).pack(side="left",padx=8)
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

    def _build_frame_send_editor(self,parent):
        parent.columnconfigure(0,weight=1)
        parent.rowconfigure(1,weight=0)
        settings=ttk.Frame(parent)
        settings.grid(row=0,column=0,sticky="ew",pady=(0,4))
        ttk.Label(settings,text="数据帧长度").pack(side="left")
        self.frame_send_length_box=ttk.Spinbox(settings,from_=1,to=64,width=5,
            textvariable=self.frame_send_length,command=self._rebuild_frame_send_cells)
        self.frame_send_length_box.pack(side="left",padx=(5,3))
        self.frame_send_length_box.bind("<Return>",lambda _event:self._rebuild_frame_send_cells())
        self.frame_send_length_box.bind("<FocusOut>",lambda _event:self._rebuild_frame_send_cells())
        ttk.Label(settings,text="字节").pack(side="left")
        ttk.Label(settings,text="字节序").pack(side="left",padx=(18,4))
        self.frame_send_endian_box=ttk.Combobox(settings,textvariable=self.frame_send_endian,
            values=("大端发送","小端发送"),width=9,state="readonly")
        self.frame_send_endian_box.pack(side="left")
        self.frame_send_endian.trace_add("write",lambda *_args:self._update_frame_send_preview())
        self.frame_send_decimal_toggle=ttk.Checkbutton(settings,text="启用十进制转换",
            variable=self.frame_send_decimal_enabled,command=self._toggle_frame_decimal)
        self.frame_send_decimal_toggle.pack(side="left",padx=(12,0))
        self.frame_send_add_button=ttk.Button(settings,text="添加数值",command=self._add_frame_send_field,
            state="disabled")
        self.frame_send_add_button.pack(side="left",padx=(6,0))

        self._frame_send_values_box=ttk.Frame(parent,padding=(5,1))
        self._frame_send_values_box.columnconfigure(0,weight=1)
        self._frame_send_inputs=ttk.Frame(self._frame_send_values_box)
        self._frame_send_inputs.grid(row=0,column=0,sticky="ew")

        self._frame_send_preview_box=ttk.Frame(parent)
        ttk.Label(self._frame_send_preview_box,text="HEX 发送数据").pack(anchor="w")
        self._frame_send_preview=ttk.Frame(self._frame_send_preview_box)
        self._frame_send_preview.pack(fill="x",expand=True)
        self._rebuild_frame_send_cells()
        self._toggle_frame_decimal()
        parent.grid(row=0,column=0,sticky="nsew")
        parent.grid_remove()

    @staticmethod
    def _valid_decimal_byte(proposed):
        return proposed in ("", "-") or proposed.isdigit() or (proposed.startswith("-") and proposed[1:].isdigit())

    @staticmethod
    def _valid_hex_byte(proposed):
        return len(proposed)<=2 and all(ch in "0123456789abcdefABCDEF" for ch in proposed)

    @staticmethod
    def _decimal_width(value):
        if value < 0:
            width=1
            while value < -(1 << (8*width-1)):
                width+=1
            return width
        return max(1,(value.bit_length()+7)//8)

    def _rebuild_frame_send_cells(self):
        try:
            size=int(self.frame_send_length.get())
            if not 1<=size<=64:raise ValueError
        except (ValueError,tk.TclError):return
        self._sync_frame_send_fields()
        self._frame_send_manual_values=self._frame_send_manual_values[:size]
        self._frame_send_manual_values.extend(["00"]*(size-len(self._frame_send_manual_values)))
        for field in self._frame_send_fields:
            field["positions"]=[p for p in field.get("positions",[]) if isinstance(p,int) and 1<=p<=size]
        for child in self._frame_send_inputs.winfo_children():child.destroy()
        for child in self._frame_send_preview.winfo_children():child.destroy()
        self._frame_send_hex_vars=[]; self._frame_send_hex_entries=[]
        validate_decimal=(self.register(self._valid_decimal_byte),"%P")
        for column in range(5):self._frame_send_inputs.columnconfigure(column,weight=0,uniform="decimalfields")
        for index,field in enumerate(self._frame_send_fields):
            row,column=divmod(index,5)
            card=tk.Frame(self._frame_send_inputs,background="#D8E0E8",padx=1,pady=1)
            card.grid(row=row,column=column,sticky="w",padx=(2,8),pady=2)
            cell=ttk.Frame(card,padding=(5,3))
            cell.pack()
            value_var=tk.StringVar(value=field["value"])
            ttk.Label(cell,text=f"数值 {index+1}").grid(row=0,column=0,sticky="w",padx=(0,3),pady=1)
            ttk.Entry(cell,textvariable=value_var,width=8,justify="center",validate="key",
                      validatecommand=validate_decimal).grid(row=0,column=1,sticky="w",padx=(0,5),pady=1)
            ttk.Label(cell,text="目标位").grid(row=0,column=2,sticky="w",padx=(0,2),pady=1)
            target_label=tk.StringVar(value=self._target_positions_text(field["positions"]))
            target_box=ttk.Menubutton(cell,textvariable=target_label,direction="below",width=8)
            target_box.grid(row=0,column=3,sticky="w",padx=(0,4),pady=1)
            ttk.Button(cell,text="×",width=2,command=lambda i=index:self._remove_frame_send_field(i)).grid(row=0,column=4,pady=1)
            field["value_var"]=value_var; field["target_label_var"]=target_label; field["target_box"]=target_box
            field["position_vars"]={}
            value_var.trace_add("write",lambda *_args,i=index:self._on_frame_send_field_edited(i))
            self._render_frame_send_selector(index)

        validate_hex=(self.register(self._valid_hex_byte),"%P")
        for index in range(size):
            row,column=divmod(index,20)
            self._frame_send_preview.columnconfigure(column,weight=1,uniform="framebytes")
            cell=ttk.Frame(self._frame_send_preview,padding=(1,1)); cell.grid(row=row,column=column,sticky="ew")
            hex_var=tk.StringVar(value=self._frame_send_manual_values[index])
            hex_var.trace_add("write",lambda *_args,i=index:self._on_frame_manual_hex_edited(i))
            hex_entry=tk.Entry(cell,textvariable=hex_var,width=4,justify="center",validate="key",
                validatecommand=validate_hex,bg="#FFFFFF",disabledbackground="#E2E5E9",disabledforeground="#6B7280")
            hex_entry.pack(); hex_entry.bind("<FocusOut>",lambda _event,i=index:self._normalize_manual_hex(i))
            self._frame_send_hex_vars.append(hex_var); self._frame_send_hex_entries.append(hex_entry)
        self._update_frame_send_preview()

    def _sync_frame_send_fields(self):
        for field in self._frame_send_fields:
            if "value_var" in field:
                field["value"]=field["value_var"].get()
                position_vars=field.get("position_vars",{})
                field["positions"]=[p for p,var in position_vars.items() if var.get()]

    @staticmethod
    def _target_positions_text(positions):
        return ", ".join(str(p) for p in sorted(positions)) if positions else "选择字节位"

    def _render_frame_send_selector(self,index):
        if index>=len(self._frame_send_fields):return
        field=self._frame_send_fields[index]; target=field.get("target_box")
        if target is None or not target.winfo_exists():return
        size=int(self.frame_send_length.get())
        used={p for i,item in enumerate(self._frame_send_fields) if i!=index for p in item.get("positions",[]) if p is not None}
        menu=tk.Menu(target,tearoff=False)
        field["position_vars"]={}; field["position_menu_indices"]={}
        selected=set(field.get("positions",[]))
        for position in range(1,size+1):
            var=tk.BooleanVar(value=position in selected)
            menu.add_checkbutton(label=f"{position} 位",variable=var,
                state="disabled" if position in used else "normal",
                command=lambda i=index:self._on_frame_send_position_changed(i))
            field["position_vars"][position]=var
            field["position_menu_indices"][position]=position-1
        target.configure(menu=menu)
        field["position_menu"]=menu
        field["target_label_var"].set(self._target_positions_text(selected))

    def _on_frame_send_field_edited(self,index):
        if index>=len(self._frame_send_fields):return
        self._sync_frame_send_fields()
        self._update_frame_send_preview()

    def _on_frame_send_position_changed(self,index):
        self._sync_frame_send_fields()
        selected_by_field=[set(field.get("positions",[])) for field in self._frame_send_fields]
        for i,field in enumerate(self._frame_send_fields):
            field["target_label_var"].set(self._target_positions_text(field["positions"]))
            used=set().union(*(s for j,s in enumerate(selected_by_field) if j!=i)) if len(selected_by_field)>1 else set()
            menu=field.get("position_menu")
            if menu is not None:
                for position,entry_index in field["position_menu_indices"].items():
                    menu.entryconfigure(entry_index,state="disabled" if position in used else "normal")
        self._update_frame_send_preview()

    def _on_frame_manual_hex_edited(self,index):
        if self._updating_frame_send_preview:return
        if index>=len(self._frame_send_hex_vars):return
        self._frame_send_manual_values[index]=self._frame_send_hex_vars[index].get().strip().upper()

    def _normalize_manual_hex(self,index):
        if index>=len(self._frame_send_hex_vars):return
        raw=self._frame_send_hex_vars[index].get().strip()
        if raw and self._valid_hex_byte(raw):
            normalized=raw.upper().zfill(2)
            self._frame_send_hex_vars[index].set(normalized)
            self._frame_send_manual_values[index]=normalized

    def _add_frame_send_field(self):
        if not self.frame_send_decimal_enabled.get():return
        self._sync_frame_send_fields()
        self._frame_send_fields.append({"value":"","positions":[]})
        self._rebuild_frame_send_cells()

    def _remove_frame_send_field(self,index):
        self._sync_frame_send_fields()
        if 0<=index<len(self._frame_send_fields):
            del self._frame_send_fields[index]
            self._rebuild_frame_send_cells()

    def _frame_decimal_assignments(self):
        if not self.frame_send_decimal_enabled.get():return {}
        self._sync_frame_send_fields()
        size=int(self.frame_send_length.get())
        assignments={}
        byteorder="little" if self.frame_send_endian.get()=="小端发送" else "big"
        for index,field in enumerate(self._frame_send_fields,1):
            raw=str(field["value"]).strip()
            if not raw:raise ValueError(f"请填写数值 {index}。")
            value=int(raw)
            width=self._decimal_width(value)
            if width>size:
                raise ValueError(f"数据帧长度不足：数值 {index} 需要 {width} 个字节，当前帧长只有 {size} 个字节。")
            positions=field.get("positions",[])
            if len(positions)<width:
                raise ValueError(f"数值 {index} 需要 {width} 个字节，请选择 {width} 个目标字节位置。")
            if any(p<1 or p>size for p in positions):
                raise ValueError(f"数值 {index} 的目标字节超出数据帧长度。")
            if len(set(positions))!=len(positions):
                raise ValueError(f"数值 {index} 的目标字节不能重复。")
            try:encoded=value.to_bytes(len(positions),byteorder=byteorder,signed=value<0)
            except OverflowError:raise ValueError(f"数值 {index} 无法放入当前数据帧。")
            for position,byte in zip(positions,encoded):
                position-=1
                if position in assignments:
                    raise ValueError("十进制数值占用了相同字节，请调整目标字节。")
                assignments[position]=byte
        return assignments

    def _frame_send_bytes(self):
        size=int(self.frame_send_length.get())
        frame=[]
        for index,raw in enumerate(self._frame_send_manual_values,1):
            raw=str(raw).strip()
            if not raw:raise ValueError(f"第 {index} 个 HEX 字节为空。")
            if len(raw)>2 or not self._valid_hex_byte(raw):
                raise ValueError(f"第 {index} 个 HEX 字节无效，请输入 00 到 FF。")
            frame.append(int(raw,16))
        for position,value in self._frame_decimal_assignments().items():frame[position]=value
        return bytes(frame[:size])

    def _update_frame_send_preview(self):
        if not hasattr(self,"_frame_send_hex_vars"):return
        self._updating_frame_send_preview=True
        try:
            assignments={}; claimed=set()
            if self.frame_send_decimal_enabled.get():
                self._sync_frame_send_fields()
                size=int(self.frame_send_length.get())
                byteorder="little" if self.frame_send_endian.get()=="小端发送" else "big"
                for field in self._frame_send_fields:
                    raw=str(field.get("value","")).strip()
                    if raw in ("", "-"):continue
                    value=int(raw); width=self._decimal_width(value)
                    positions=field.get("positions",[])
                    claimed.update(p-1 for p in positions if p is not None and 1<=p<=size)
                    if len(positions)<width or any(p is None or p<1 or p>size for p in positions):continue
                    try:encoded=value.to_bytes(len(positions),byteorder=byteorder,signed=value<0)
                    except OverflowError:continue
                    for position,byte in zip(positions,encoded):
                        if position-1 not in assignments:assignments[position-1]=byte
            for index,(hex_var,entry) in enumerate(zip(self._frame_send_hex_vars,self._frame_send_hex_entries)):
                if index in assignments:
                    hex_var.set(f"{assignments[index]:02X}")
                    entry.configure(state="disabled")
                elif index in claimed:
                    hex_var.set("--")
                    entry.configure(state="disabled")
                else:
                    hex_var.set(self._frame_send_manual_values[index])
                    entry.configure(state="normal",bg="#FFFFFF")
        except (ValueError,TypeError,OverflowError,tk.TclError):
            for index,(hex_var,entry) in enumerate(zip(self._frame_send_hex_vars,self._frame_send_hex_entries)):
                hex_var.set(self._frame_send_manual_values[index])
                entry.configure(state="normal",bg="#FFFFFF")
        finally:
            self._updating_frame_send_preview=False

    def _toggle_frame_decimal(self):
        enabled=self.frame_send_decimal_enabled.get()
        self.frame_send_add_button.configure(state="normal" if enabled else "disabled")
        if enabled:
            self._frame_send_values_box.grid(row=1,column=0,sticky="nsew",pady=(0,4))
            self._frame_send_preview_box.grid(row=2,column=0,sticky="ew")
            self.frame_send_panel.rowconfigure(1,weight=0,minsize=0)
            self.frame_send_panel.rowconfigure(2,weight=0)
        else:
            self._frame_send_values_box.grid_remove()
            self._frame_send_preview_box.grid(row=1,column=0,sticky="ew")
            self.frame_send_panel.rowconfigure(1,weight=0,minsize=0)
            self.frame_send_panel.rowconfigure(2,weight=0,minsize=0)
        self._update_frame_send_preview()

    def _set_send_mode(self):
        if self.sendmode.get()=="数据帧":
            self.sendbox.grid_remove()
            self.frame_send_panel.grid()
            self._update_frame_send_preview()
        else:
            self.frame_send_panel.grid_remove()
            self.sendbox.grid()
        self.after_idle(self._adjust_send_split)

    def _adjust_send_split(self):
        if not hasattr(self,"serial_panes") or not self.serial_panes.winfo_exists():return
        height=self.serial_panes.winfo_height()
        if height>0:
            fraction=0.60
            self.serial_panes.sashpos(0,int(height*fraction))

    def _update_receive_layout(self,changed=None):
        if not self.show_hex.get() and not self.show_text.get():
            if changed=="text":
                self.show_text.set(True)
            else:
                self.show_hex.set(True)
        for pane in self.receive_views.panes():
            self.receive_views.forget(pane)
        if self.show_hex.get():
            self.receive_views.add(self.hex_view,weight=1)
        if self.show_text.get():
            self.receive_views.add(self.text_view,weight=1)
        self.refresh_view()

    def build_parse_page(self, page):
        page.columnconfigure(0,weight=1)
        page.rowconfigure(0,weight=1)
        self._parse_split=ttk.Panedwindow(page,orient="vertical")
        self._parse_split.grid(row=0,column=0,sticky="nsew")
        cfg=ttk.LabelFrame(self._parse_split,text="帧设置",padding=8)
        cfg.columnconfigure(1,weight=1)

        frame_group=ttk.LabelFrame(cfg,text="数据帧",padding=7)
        frame_group.grid(row=0,column=0,sticky="nsw",padx=(0,8))
        ttk.Label(frame_group,text="帧长（字节，含帧头）").grid(row=0,column=0,sticky="w")
        self.frame_len=tk.StringVar(value="8")
        ttk.Spinbox(frame_group,from_=1,to=512,textvariable=self.frame_len,width=7).grid(row=1,column=0,sticky="w",pady=(4,0))

        header_group=ttk.LabelFrame(cfg,text="帧头检测",padding=7)
        header_group.grid(row=0,column=1,sticky="ew")
        header_group.columnconfigure(0,weight=1)
        self.header_enabled=tk.BooleanVar(value=False)
        header_controls=ttk.Frame(header_group)
        header_controls.grid(row=0,column=0,sticky="ew")
        ttk.Checkbutton(header_controls,text="启用帧头检测",variable=self.header_enabled,command=self._header_state).pack(side="left")
        ttk.Label(header_controls,text="帧头长度").pack(side="left",padx=(16,4))
        self.header_length=tk.StringVar(value="2")
        self.header_length_box=ttk.Combobox(header_controls,textvariable=self.header_length,
            values=tuple(str(n) for n in range(1,17)),width=3,state="readonly")
        self.header_length_box.pack(side="left")
        ttk.Label(header_controls,text="字节").pack(side="left",padx=(4,0))
        self.header_values=[]
        self.header_entries=[]
        self.header_inputs=ttk.Frame(header_group)
        self.header_inputs.grid(row=1,column=0,sticky="w",pady=(5,0))
        self.header_length.trace_add("write",self._rebuild_header_inputs)
        self.header_help=ttk.Label(header_group,text="帧头用于定位每帧起点；开启后只解析匹配的数据，帧头仍保留在原始帧中。",
                  wraplength=720,justify="left",foreground="#657487")
        self.header_help.grid(row=2,column=0,sticky="w",pady=(5,0))
        self._rebuild_header_inputs()
        config_actions=ttk.Frame(cfg)
        config_actions.grid(row=1,column=0,columnspan=2,sticky="e",pady=(6,0))
        config_buttons=ttk.Frame(config_actions)
        config_buttons.pack(side="left")
        ttk.Button(config_buttons,text="加载配置",command=self.load_config).pack(side="right",padx=(6,0))
        ttk.Button(config_buttons,text="保存配置",command=self.save_config).pack(side="right")

        panes=ttk.Panedwindow(self._parse_split,orient="vertical")
        lower_area=ttk.Frame(panes)
        lower_area.columnconfigure(0,weight=1)
        lower_area.rowconfigure(1,weight=1)

        fields=ttk.LabelFrame(panes,text="字段定义（字节位置从 1 开始；每个字节只能分给一个字段）",padding=7)
        fields.columnconfigure(0,weight=1)
        fields.rowconfigure(0,weight=1)
        self.field_tree=ttk.Treeview(fields,columns=("name","length","positions","endian","base"),show="headings",height=7,selectmode="browse")
        for col,title,width in (("name","字段名",180),("length","长度",70),("positions","对应字节",280),("endian","字节序",110),("base","显示进制",90)):
            self.field_tree.heading(col,text=title)
            self.field_tree.column(col,width=width,anchor="w" if col in ("name","positions") else "center")
        self.field_tree.grid(row=0,column=0,rowspan=2,sticky="nsew")
        fbtns=ttk.Frame(fields)
        fbtns.grid(row=0,column=1,sticky="ns",padx=(8,0))
        ttk.Button(fbtns,text="添加字段",command=self.add_field).pack(fill="x",pady=(0,4))
        ttk.Button(fbtns,text="编辑字段",command=self.edit_field).pack(fill="x",pady=4)
        ttk.Button(fbtns,text="删除字段",command=self.delete_field).pack(fill="x",pady=4)
        self.fields=[]
        self._wave_vars={}
        self._wave_samples=deque(maxlen=20000)
        self._wave_break_next_sample=False
        self._wave_window=None
        self._wave_controls=None
        self._wave_redraw_after=None
        self._wave_auto_button=None
        self._wave_time_origin=None
        self._wave_view_span=30.0
        self._wave_view_start=0.0
        self._wave_view_end=30.0
        self._wave_fit=False
        self._wave_manual_view=False

        run=ttk.Frame(lower_area)
        run.grid(row=0,column=0,sticky="ew",pady=(0,7))
        self.parse_running=tk.BooleanVar(value=False)
        self.parse_button=ttk.Button(run,text="开始持续解析",command=self.toggle_parse)
        self.parse_button.pack(side="left")
        ttk.Label(run,text="解析刷新间隔").pack(side="left",padx=(12,4))
        self.parse_interval=tk.StringVar(value="1")
        ttk.Spinbox(run,from_=0.1,to=60,increment=0.1,textvariable=self.parse_interval,width=6).pack(side="left")
        ttk.Label(run,text="秒   串口仍持续接收；仅完整帧会进入结果").pack(side="left",padx=6)
        self.frame_count=tk.StringVar(value="已解析 0 帧")
        ttk.Label(run,textvariable=self.frame_count).pack(side="right")

        result=ttk.Panedwindow(lower_area,orient="horizontal")
        result.grid(row=1,column=0,sticky="nsew")
        rawpane=ttk.LabelFrame(result,text="原始数据帧",padding=6)
        valpane=ttk.LabelFrame(result,text="字段解析",padding=6)
        for pane in (rawpane,valpane):
            pane.rowconfigure(0,weight=1); pane.columnconfigure(0,weight=1)
        self.raw_frames=tk.Text(rawpane,font=("Consolas",10),wrap="none",state="disabled")
        self.raw_frames.grid(row=0,column=0,sticky="nsew")
        raw_sb=ttk.Scrollbar(rawpane,command=self.raw_frames.yview)
        raw_sb.grid(row=0,column=1,sticky="ns")
        self.raw_frames.configure(yscrollcommand=raw_sb.set)
        self.parsed=tk.Text(valpane,font=("Consolas",10),wrap="word",state="disabled")
        self.parsed.grid(row=0,column=0,sticky="nsew")
        val_sb=ttk.Scrollbar(valpane,command=self.parsed.yview)
        val_sb.grid(row=0,column=1,sticky="ns")
        self.parsed.configure(yscrollcommand=val_sb.set)
        panes.add(fields,weight=1); panes.add(lower_area,weight=2)
        result.add(rawpane,weight=1); result.add(valpane,weight=1)
        self._parse_split.add(cfg,weight=0)
        self._parse_split.add(panes,weight=1)
        def set_initial_parse_split():
            height=panes.winfo_height()
            if height>0:
                panes.sashpos(0,int(height*0.34))
            total_height=self._parse_split.winfo_height()
            if total_height>0:
                self._parse_split.sashpos(0,min(250,int(total_height*0.36)))
        page.after(300,set_initial_parse_split)
        footer=ttk.Frame(page)
        footer.grid(row=1,column=0,sticky="ew",pady=(5,0))
        footer.columnconfigure(0,weight=1)
        ttk.Label(footer,text="长时间没有解析结果？请检查帧长、帧头检测是否开启，以及帧头内容是否准确。",
                  foreground="#657487",anchor="w").grid(row=0,column=0,sticky="ew")
        ttk.Button(footer,text="波形分析",command=self.open_waveform).grid(row=0,column=1,sticky="e",padx=(8,0))
        self._parse_pending=bytearray()
        self._parse_offset=0
        self._parse_after=None
        self._parsed_frames=0
        self._parse_raw_lines=[]
        self._parse_value_lines=[]
        self.settext(self.raw_frames,"开始持续解析后，完整帧会显示在这里。")
        self.settext(self.parsed,"添加字段定义后，字段数值会显示在这里。")

    @staticmethod
    def _valid_hex_byte(value):
        return len(value)<=2 and all(char in "0123456789abcdefABCDEF" for char in value)

    def _rebuild_header_inputs(self,*_):
        try:
            count=int(self.header_length.get())
        except (TypeError,ValueError):
            return
        if not 1<=count<=16:
            return
        while len(self.header_values)<count:
            self.header_values.append(tk.StringVar())
        del self.header_values[count:]
        for widget in self.header_inputs.winfo_children():
            widget.destroy()
        self.header_entries=[]
        validator=(self.register(self._valid_hex_byte),"%P")
        for index,value in enumerate(self.header_values):
            entry=ttk.Entry(self.header_inputs,textvariable=value,width=3,justify="center",
                            validate="key",validatecommand=validator)
            entry.grid(row=0,column=index,sticky="w",padx=(0,4))
            self.header_entries.append(entry)
        ttk.Label(self.header_inputs,text="请输入十六进制数").grid(row=0,column=count,sticky="w",padx=(4,0))
        self._header_state()

    def _header_state(self):
        enabled=self.header_enabled.get()
        self.header_length_box.configure(state="readonly" if enabled else "disabled")
        for entry in self.header_entries:
            entry.configure(state="normal" if enabled else "disabled")
        if enabled:
            self.header_inputs.grid()
            self.header_help.grid()
        else:
            self.header_inputs.grid_remove()
            self.header_help.grid_remove()

    def _frame_size(self):
        try:
            size=int(self.frame_len.get())
            if not 1 <= size <= 512: raise ValueError()
            return size
        except (TypeError,ValueError):
            raise ValueError("帧长必须是 1 到 512 之间的整数。")

    def _selected_positions(self, frame_size, selected=None):
        dlg=tk.Toplevel(self)
        dlg.title("字段设置")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(True,True)
        dlg.columnconfigure(1,weight=1)
        ttk.Label(dlg,text="字段名").grid(row=0,column=0,sticky="w",padx=10,pady=(10,5))
        name=tk.StringVar(value=(selected or {}).get("name",""))
        name_entry=ttk.Entry(dlg,textvariable=name,width=25)
        name_entry.grid(row=0,column=1,columnspan=3,sticky="ew",padx=(4,10),pady=(10,5))
        ttk.Label(dlg,text="长度").grid(row=1,column=0,sticky="w",padx=10,pady=5)
        length=tk.StringVar(value=str((selected or {}).get("length",1)))
        ttk.Spinbox(dlg,from_=1,to=frame_size,textvariable=length,width=6).grid(row=1,column=1,sticky="w",padx=4,pady=5)
        ttk.Label(dlg,text="选择对应字节（按位置升序读取）").grid(row=2,column=0,columnspan=4,sticky="w",padx=10,pady=(5,2))
        lbframe=ttk.Frame(dlg)
        lbframe.grid(row=3,column=0,columnspan=4,sticky="nsew",padx=10)
        dlg.rowconfigure(3,weight=1)
        positions=tk.Listbox(lbframe,selectmode="multiple",height=min(12,max(4,frame_size)),exportselection=False)
        lbscroll=ttk.Scrollbar(lbframe,command=positions.yview)
        positions.configure(yscrollcommand=lbscroll.set)
        positions.pack(side="left",fill="both",expand=True)
        lbscroll.pack(side="right",fill="y")
        for i in range(1,frame_size+1):
            occupied=next((f["name"] for f in self.fields if i in f["positions"] and (selected is None or f is not selected)),None)
            suffix=f"（已分配：{occupied}）" if occupied else ""
            positions.insert("end",f"第 {i} 字节{suffix}")
            if occupied: positions.itemconfigure(i-1,foreground="#9aa5b1")
        chosen=set((selected or {}).get("positions",[]))
        for i in range(1,frame_size+1):
            if i in chosen: positions.selection_set(i-1)
        endian=tk.StringVar(value=(selected or {}).get("endian","大端读取"))
        base=tk.StringVar(value=(selected or {}).get("base","十进制"))
        signed=tk.BooleanVar(value=(selected or {}).get("signed",False))
        ttk.Label(dlg,text="多字节字节序").grid(row=4,column=0,sticky="w",padx=10,pady=7)
        endian_box=ttk.Combobox(dlg,textvariable=endian,values=("大端读取","小端读取"),state="readonly",width=12)
        endian_box.grid(row=4,column=1,sticky="w",padx=4,pady=7)
        ttk.Label(dlg,text="进制转换").grid(row=4,column=2,sticky="e",padx=4,pady=7)
        ttk.Combobox(dlg,textvariable=base,values=("二进制","八进制","十进制","十六进制"),state="readonly",width=10).grid(row=4,column=3,sticky="w",padx=(4,10),pady=7)
        ttk.Checkbutton(dlg,text="有符号整数",variable=signed).grid(row=5,column=0,columnspan=2,sticky="w",padx=10,pady=(0,5))
        result={"value":None}
        def save():
            field_name=name.get().strip()
            try: n=int(length.get())
            except ValueError:
                messagebox.showerror("字段长度无效","请输入有效的字节长度。",parent=dlg); return
            pos=[int(x)+1 for x in positions.curselection()]
            if not field_name:
                messagebox.showwarning("缺少字段名","请填写字段名。",parent=dlg); return
            if not 1<=n<=frame_size:
                messagebox.showwarning("字段长度无效",f"字段长度必须在 1 到 {frame_size} 字节之间。",parent=dlg); return
            if not pos or len(pos)!=n:
                messagebox.showwarning("字节数量不匹配",f"长度为 {n} 字节，请恰好选择 {n} 个字节位置。",parent=dlg); return
            result["value"]={"name":field_name,"length":n,"positions":pos,"endian":endian.get(),"base":base.get(),"signed":signed.get()}
            dlg.destroy()
        btns=ttk.Frame(dlg)
        btns.grid(row=6,column=0,columnspan=4,sticky="e",padx=10,pady=(2,10))
        ttk.Button(btns,text="取消",command=dlg.destroy).pack(side="right",padx=(6,0))
        ttk.Button(btns,text="保存",command=save).pack(side="right")
        name_entry.focus_set()
        dlg.geometry("430x500")
        self.wait_window(dlg)
        return result["value"]

    def _refresh_fields(self):
        self._ensure_field_colors()
        self.field_tree.delete(*self.field_tree.get_children())
        for i,f in enumerate(self.fields):
            positions="、".join(map(str,f["positions"]))
            endian=f["endian"] if f["length"]>1 else "—"
            self.field_tree.insert("","end",iid=str(i),values=(f["name"],f["length"],positions,endian,f["base"]))
        self._sync_wave_controls()

    @staticmethod
    def _default_wave_color(index):
        palette=("#168AAD","#E76F51","#2A9D8F","#8E5CC2","#E9A11B","#D9488B",
                 "#577590","#55A630","#BC4749","#0077B6","#6D597A","#7F5539")
        if index<len(palette):return palette[index]
        hue=(index*0.618033988749895)%1.0
        red,green,blue=colorsys.hsv_to_rgb(hue,0.72,0.78)
        return "#{:02X}{:02X}{:02X}".format(round(red*255),round(green*255),round(blue*255))

    @staticmethod
    def _valid_wave_color(color):
        return isinstance(color,str) and re.fullmatch(r"#[0-9A-Fa-f]{6}",color) is not None

    def _ensure_field_colors(self):
        used=set()
        for field in self.fields:
            color=field.get("color")
            if not self._valid_wave_color(color) or color.upper() in used:
                index=len(used)
                color=self._default_wave_color(index)
                while color.upper() in used:
                    index+=1
                    color=self._default_wave_color(index)
                field["color"]=color
            used.add(field["color"].upper())

    def open_waveform(self):
        if self._wave_window is not None and self._wave_window.winfo_exists():
            self._wave_window.deiconify()
            self._wave_window.lift()
            self._sync_wave_controls()
            self._schedule_wave_redraw(0)
            return

        win=tk.Toplevel(self)
        self._wave_window=win
        win.title("UART 波形分析")
        win.geometry("1100x720")
        win.minsize(760,480)
        win.transient(self)
        win.protocol("WM_DELETE_WINDOW",self._close_waveform)
        self._wave_samples.clear()
        self._wave_time_origin=time.monotonic()
        self._wave_break_next_sample=False
        self._wave_view_span=30.0
        self._wave_view_start=0.0
        self._wave_view_end=30.0
        self._wave_fit=False
        self._wave_manual_view=False
        win.columnconfigure(0,weight=1)
        win.rowconfigure(1,weight=1)

        toolbar=ttk.LabelFrame(win,text="显示字段",padding=(8,5))
        toolbar.grid(row=0,column=0,sticky="ew",padx=10,pady=(10,6))
        toolbar.columnconfigure(0,weight=1)
        self._wave_controls=ttk.Frame(toolbar)
        self._wave_controls.grid(row=0,column=0,sticky="ew")
        wave_actions=ttk.Frame(toolbar)
        wave_actions.grid(row=0,column=1,sticky="e",padx=(8,0))
        self._wave_auto_button=ttk.Button(wave_actions,text="Auto",command=self._wave_auto)
        self._wave_auto_button.pack(side="left")

        graph=ttk.Frame(win)
        graph.grid(row=1,column=0,sticky="nsew",padx=10)
        graph.rowconfigure(0,weight=1)
        graph.columnconfigure(0,weight=1)
        self._wave_canvas=tk.Canvas(graph,bg="#ffffff",highlightthickness=1,highlightbackground="#dce3eb")
        self._wave_canvas.grid(row=0,column=0,sticky="nsew")
        self._wave_canvas.bind("<Configure>",lambda _event:self._schedule_wave_redraw(0))
        self._wave_canvas.bind("<MouseWheel>",self._wave_zoom)
        self._wave_canvas.bind("<ButtonPress-1>",self._wave_pan_start)
        self._wave_canvas.bind("<B1-Motion>",self._wave_pan_move)
        self._wave_canvas.bind("<Motion>",self._wave_hover_move)
        self._wave_canvas.bind("<Leave>",self._wave_hover_leave)

        ttk.Label(win,text="时间从打开波形窗口起算（0 秒）；滚轮缩放时间轴，按住鼠标左键拖动；多字段共用原值纵轴。",
                  foreground="#657487",anchor="w").grid(row=2,column=0,sticky="ew",padx=12,pady=(6,10))
        self._sync_wave_controls()
        self._schedule_wave_redraw(0)

    def _close_waveform(self):
        if self._wave_redraw_after is not None:
            try:self.after_cancel(self._wave_redraw_after)
            except tk.TclError:pass
            self._wave_redraw_after=None
        win=self._wave_window
        self._wave_window=None
        if win is not None:
            try:win.destroy()
            except tk.TclError:pass

    def _sync_wave_controls(self):
        win=self._wave_window
        if win is None or not win.winfo_exists():return
        for child in self._wave_controls.winfo_children():child.destroy()
        names={field["name"] for field in self.fields}
        old_vars=self._wave_vars
        previously_known=names.intersection(old_vars)
        self._wave_vars={name:var for name,var in old_vars.items() if name in names}
        if not self.fields:
            ttk.Label(self._wave_controls,text="请先添加字段定义。",foreground="#657487").pack(side="left")
        else:
            ttk.Label(self._wave_controls,text="选择字段：").pack(side="left",padx=(0,8))
            for index,field in enumerate(self.fields):
                name=field["name"]
                var=self._wave_vars.get(name)
                if var is None:
                    var=tk.BooleanVar(value=(not previously_known and index==0))
                    self._wave_vars[name]=var
                item=ttk.Frame(self._wave_controls)
                item.pack(side="left",padx=(0,12))
                ttk.Checkbutton(item,text=name,variable=var,
                    command=lambda:self._schedule_wave_redraw(0)).pack(side="left")
                color=field.get("color",self._default_wave_color(index))
                tk.Button(item,text="",width=2,relief="solid",bd=1,bg=color,activebackground=color,
                    cursor="hand2",command=lambda field_name=name:self._choose_wave_color(field_name)).pack(side="left",padx=(2,0))
        self._schedule_wave_redraw(0)

    def _choose_wave_color(self,name):
        field=next((item for item in self.fields if item["name"]==name),None)
        if field is None:return
        chosen=colorchooser.askcolor(color=field.get("color",self._default_wave_color(0)),
                                     title=f"选择“{name}”的波形颜色",parent=self._wave_window)[1]
        if not chosen:return
        chosen=chosen.upper()
        if any(other is not field and other.get("color","").upper()==chosen for other in self.fields):
            messagebox.showwarning("颜色已被使用","每个字段需要使用不同颜色，请为该字段选择另一种颜色。",parent=self._wave_window)
            return
        field["color"]=chosen
        self._sync_wave_controls()
        self._schedule_wave_redraw(0)

    def _wave_latest_time(self):
        return self._wave_samples[-1]["time"] if self._wave_samples else 0.0

    def _wave_current_time_range(self):
        if self._wave_manual_view:
            return self._wave_view_start,self._wave_view_end
        latest=self._wave_latest_time()
        if self._wave_fit:
            return 0.0,max(10.0,latest)
        span=max(0.2,self._wave_view_span)
        end=max(span,latest)
        return max(0.0,end-span),end

    def _wave_values_in_range(self,name,start,end):
        return [sample["values"][name] for sample in self._wave_samples
                if start<=sample["time"]<=end and name in sample["values"]]

    def _wave_auto(self):
        self._wave_fit=True
        self._wave_manual_view=False
        self._wave_view_start=0.0
        self._wave_view_end=max(10.0,self._wave_latest_time())
        self._wave_view_span=self._wave_view_end
        self._schedule_wave_redraw(0)

    def _wave_zoom(self,event):
        start,end=self._wave_current_time_range()
        span=end-start
        factor=0.8 if event.delta>0 else 1.25
        new_span=max(0.2,min(86400.0,span*factor))
        width=max(1,self._wave_canvas.winfo_width()-153)
        fraction=max(0.0,min(1.0,(event.x-125)/width))
        anchor=start+fraction*span
        new_start=max(0.0,anchor-fraction*new_span)
        self._wave_view_start=new_start
        self._wave_view_end=new_start+new_span
        self._wave_view_span=new_span
        self._wave_fit=False
        self._wave_manual_view=True
        self._schedule_wave_redraw(0)
        return "break"

    def _wave_pan_start(self,event):
        self._wave_drag_start_x=event.x
        self._wave_drag_start_range=self._wave_current_time_range()

    def _wave_pan_move(self,event):
        start,end=self._wave_drag_start_range
        span=end-start
        width=max(1,self._wave_canvas.winfo_width()-153)
        shift=-(event.x-self._wave_drag_start_x)*span/width
        new_start=max(0.0,start+shift)
        self._wave_view_start=new_start
        self._wave_view_end=new_start+span
        self._wave_view_span=span
        self._wave_fit=False
        self._wave_manual_view=True
        self._schedule_wave_redraw(0)

    def _wave_hover_leave(self,_event=None):
        canvas=getattr(self,"_wave_canvas",None)
        if canvas is not None:
            canvas.delete("wave-hover")

    def _wave_hover_move(self,event):
        canvas=self._wave_canvas
        canvas.delete("wave-hover")
        points=getattr(self,"_wave_hover_points",())
        if not points:return
        best=None
        for point in points:
            distance=(point[0]-event.x)**2+(point[1]-event.y)**2
            if best is None or distance<best[0]:best=(distance,point)
        if best is None or best[0]>18**2:return
        _,(x,y,name,stamp,value,color)=best
        label=f"{name}  {stamp:.3f} 秒  {value}"
        text=canvas.create_text(event.x+14,event.y-14,text=label,anchor="sw",fill="#17212b",
                                font=("Microsoft YaHei UI",10,"bold"),tags=("wave-hover",))
        bounds=canvas.bbox(text)
        if bounds:
            canvas.create_rectangle(bounds[0]-6,bounds[1]-4,bounds[2]+6,bounds[3]+4,
                                    fill="#fffbe6",outline=color,width=1,tags=("wave-hover",))
            canvas.tag_raise(text)
        canvas.create_oval(x-5,y-5,x+5,y+5,fill="#ffffff",outline=color,width=2,
                           tags=("wave-hover",))

    def _schedule_wave_redraw(self,delay=120):
        if self._wave_window is None or not self._wave_window.winfo_exists():return
        if self._wave_redraw_after is not None:
            try:self.after_cancel(self._wave_redraw_after)
            except tk.TclError:pass
        self._wave_redraw_after=self.after(delay,self._draw_waveform)

    def _draw_waveform(self):
        self._wave_redraw_after=None
        if self._wave_window is None or not self._wave_window.winfo_exists():return
        canvas=self._wave_canvas
        canvas.delete("all")
        width=max(canvas.winfo_width(),760)
        height=max(canvas.winfo_height(),400)
        if not self.fields:
            canvas.create_text(width/2,height/2,text="请先在数据解析页添加字段定义。",fill="#657487",
                               font=("Microsoft YaHei UI",11))
            return
        selected=[field for field in self.fields
                  if self._wave_vars.get(field["name"]) is not None and self._wave_vars[field["name"]].get()]
        if not selected:
            self._wave_hover_points=[]
            canvas.create_text(width/2,height/2,text="请至少勾选一个字段以显示波形。",fill="#657487",
                               font=("Microsoft YaHei UI",11))
            return
        start,end=self._wave_current_time_range()
        if end<=start:end=start+1.0
        left,right=125,width-28
        legend_rows=max(1,(len(selected)+2)//3)
        plot_top,plot_bottom=45+legend_rows*24,height-76
        plot_width=max(1,right-left)
        columns=min(3,len(selected))
        item_width=max(1,plot_width/columns)
        field_series={}
        for index,field in enumerate(selected):
            name=field["name"]
            series=[sample for sample in self._wave_samples
                    if start-1.0<=sample["time"]<=end+1.0 and name in sample["values"]]
            max_points=max(600,width*2)
            segments=[]
            segment=[]
            for sample in series:
                if sample.get("break_before") and segment:
                    segments.append(segment)
                    segment=[]
                segment.append(sample)
            if segment:segments.append(segment)
            if sum(map(len,segments))>max_points and segments:
                remaining=max_points
                reduced=[]
                for segment_index,segment in enumerate(segments):
                    budget=max(1,remaining-(len(segments)-segment_index-1))
                    if len(segment)>budget and budget>1:
                        step=(len(segment)-1)/(budget-1)
                        segment=[segment[min(len(segment)-1,int(point*step))] for point in range(budget)]
                    elif len(segment)>budget:
                        segment=segment[-1:]
                    reduced.append(segment)
                    remaining=max(0,remaining-len(segment))
                segments=reduced
            values=self._wave_values_in_range(name,start,end)
            if not values:
                values=[sample["values"][name] for sample in self._wave_samples if name in sample["values"]]
            current=next((sample["values"][name] for sample in reversed(self._wave_samples)
                          if name in sample["values"]),None)
            low_value=min(values) if values else None
            high_value=max(values) if values else None
            field_series[name]=(segments,values,current,low_value,high_value)
            row,column=divmod(index,columns)
            x=left+column*item_width
            y=24+row*24
            color=field.get("color",self._default_wave_color(index))
            canvas.create_line(x,y,x+19,y,fill=color,width=3)
            range_text=(f"{low_value:.5g}–{high_value:.5g}" if values else "等待数据")
            canvas.create_text(x+25,y,text=f"{name}  当前 {current if current is not None else '—'}  范围 {range_text}",
                               anchor="w",fill=color,font=("Microsoft YaHei UI",9,"bold"))

        all_values=[value for _,values,_,_,_ in field_series.values() for value in values]
        if all_values:
            low=min(all_values);high=max(all_values)
            padding=max(abs(low)*0.05,1) if low==high else (high-low)*0.08
            low-=padding;high+=padding
        else:
            low,high=-1.0,1.0

        canvas.create_text(15,(plot_top+plot_bottom)/2,text="数值（原值）",angle=90,
                           fill="#657487",font=("Microsoft YaHei UI",9))
        for index in range(11):
            fraction=index/10
            y=plot_top+fraction*(plot_bottom-plot_top)
            tick=high-fraction*(high-low)
            canvas.create_line(left,y,right,y,fill="#e5ebf1" if index in (0,5,10) else "#f0f3f6")
            canvas.create_text(left-10,y,text=f"{tick:.5g}",anchor="e",fill="#657487",font=("Consolas",9))
        for index in range(6):
            fraction=index/5
            x=left+fraction*plot_width
            elapsed=start+fraction*(end-start)
            canvas.create_line(x,plot_top,x,plot_bottom,fill="#edf1f5")
            canvas.create_text(x,plot_bottom+21,text=f"{elapsed:.1f}",anchor="center",fill="#657487",font=("Consolas",9))

        has_data=False
        self._wave_hover_points=[]
        for field in selected:
            segments,values,current,_,_=field_series[field["name"]]
            if not segments:continue
            has_data=True
            color=field.get("color",self._default_wave_color(0))
            for segment in segments:
                points=[]
                for sample in segment:
                    stamp=sample["time"]
                    value=sample["values"][field["name"]]
                    x=left+(stamp-start)/(end-start)*plot_width
                    y=plot_bottom-(value-low)/(high-low)*(plot_bottom-plot_top)
                    points.extend((x,y))
                    self._wave_hover_points.append((x,y,field["name"],stamp,value,color))
                if len(points)>=4:
                    canvas.create_line(*points,fill=color,width=2,tags=(f"wave:{field['name']}",))
                elif len(points)==2:
                    x,y=points
                    canvas.create_oval(x-4,y-4,x+4,y+4,fill=color,outline=color,tags=(f"wave:{field['name']}",))
        if not has_data:
            canvas.create_text(width/2,(plot_top+plot_bottom)/2,text="等待完整数据帧……",fill="#8a98a8",
                               font=("Microsoft YaHei UI",11))
        canvas.create_text((left+right)/2,height-20,text="时间（秒，从 0 开始）",fill="#425466",
                           font=("Microsoft YaHei UI",9))

    def add_field(self):
        try: n=self._frame_size()
        except ValueError as e:
            messagebox.showwarning("帧长无效",str(e)); return
        field=self._selected_positions(n)
        if field:
            if any(f["name"]==field["name"] for f in self.fields):
                messagebox.showwarning("字段名重复","请使用不同的字段名。"); return
            self.fields.append(field); self._refresh_fields()

    def edit_field(self):
        sel=self.field_tree.selection()
        if not sel: return
        i=int(sel[0])
        try: n=self._frame_size()
        except ValueError as e:
            messagebox.showwarning("帧长无效",str(e)); return
        original=self.fields[i]
        field=self._selected_positions(n,original)
        if field:
            if any(j!=i and f["name"]==field["name"] for j,f in enumerate(self.fields)):
                messagebox.showwarning("字段名重复","请使用不同的字段名。"); return
            field["color"]=original.get("color",self._default_wave_color(i))
            self.fields[i]=field; self._refresh_fields()

    def delete_field(self):
        sel=self.field_tree.selection()
        if sel:
            del self.fields[int(sel[0])]; self._refresh_fields()

    def _header_bytes(self):
        if not self.header_enabled.get(): return b""
        values=[value.get().strip() for value in self.header_values]
        if not values or any(len(value)!=2 or not self._valid_hex_byte(value) for value in values):
            raise ValueError("请将每个帧头输入框填写为两位十六进制数，例如 E2、80。")
        return bytes(int(value,16) for value in values)

    def _config_data(self):
        frame_size=self._frame_size()
        header=self._header_bytes()
        if header and len(header)>frame_size:
            raise ValueError("帧头长度不能大于整帧长度。")
        used=set()
        fields=[]
        for field in self.fields:
            positions=[int(p) for p in field["positions"]]
            if len(positions)!=int(field["length"]) or any(p<1 or p>frame_size for p in positions):
                raise ValueError(f"字段“{field['name']}”的长度或字节位置不符合当前帧长。")
            if used.intersection(positions):
                raise ValueError("字段配置中存在重复分配的字节位置。")
            used.update(positions)
            fields.append({
                "name":field["name"],"length":int(field["length"]),"positions":positions,
                "endian":field["endian"],"base":field["base"],"signed":bool(field["signed"]),
                "color":field.get("color",self._default_wave_color(len(fields)))
            })
        interval=float(self.parse_interval.get())
        if not 0.1<=interval<=60:
            raise ValueError("解析刷新间隔需在 0.1 到 60 秒之间。")
        return {
            "version":1,
            "name":"UART 数据帧配置",
            "frame_length":frame_size,
            "header_enabled":bool(self.header_enabled.get()),
            "header_hex":" ".join(f"{byte:02X}" for byte in header),
            "parse_interval_seconds":interval,
            "fields":fields
        }

    @staticmethod
    def _validate_config(data):
        if not isinstance(data,dict) or data.get("version")!=1:
            raise ValueError("配置文件格式或版本不受支持。")
        try: frame_size=int(data["frame_length"])
        except (KeyError,TypeError,ValueError): raise ValueError("配置中的帧长无效。")
        if not 1<=frame_size<=512: raise ValueError("配置中的帧长必须在 1 到 512 之间。")
        header_enabled=bool(data.get("header_enabled",False))
        header_hex=str(data.get("header_hex",""))
        if header_enabled:
            try: header=bytes(int(part,16) for part in header_hex.replace(","," ").replace("，"," ").split())
            except ValueError: raise ValueError("配置中的帧头不是有效的十六进制字节。")
            if not header or len(header)>min(frame_size,16): raise ValueError("配置中的帧头长度无效（最多 16 字节，且不能超过帧长）。")
            header_hex=" ".join(f"{byte:02X}" for byte in header)
        else:
            header_hex=""
        try: interval=float(data.get("parse_interval_seconds",1))
        except (TypeError,ValueError): raise ValueError("配置中的刷新间隔无效。")
        if not 0.1<=interval<=60: raise ValueError("配置中的刷新间隔需在 0.1 到 60 秒之间。")
        allowed_endian={"大端读取","小端读取"}
        allowed_base={"二进制","八进制","十进制","十六进制"}
        fields=data.get("fields",[])
        if not isinstance(fields,list): raise ValueError("配置中的字段列表无效。")
        normalized=[]; used=set(); names=set(); colors=set()
        for item in fields:
            if not isinstance(item,dict): raise ValueError("配置中的字段内容无效。")
            name=str(item.get("name","")).strip()
            try:
                length=int(item["length"])
                positions=[int(p) for p in item["positions"]]
            except (KeyError,TypeError,ValueError): raise ValueError(f"字段“{name or '?'}”的长度或字节位置无效。")
            endian=item.get("endian","大端读取")
            base=item.get("base","十进制")
            if not name or name in names: raise ValueError("字段名不能为空且不能重复。")
            if not 1<=length<=frame_size or len(positions)!=length:
                raise ValueError(f"字段“{name}”的长度与所选字节数量不匹配。")
            if any(p<1 or p>frame_size for p in positions): raise ValueError(f"字段“{name}”的字节位置超出帧长。")
            if len(set(positions))!=len(positions) or used.intersection(positions):
                raise ValueError(f"字段“{name}”与其他字段重复占用了字节。")
            if endian not in allowed_endian or base not in allowed_base:
                raise ValueError(f"字段“{name}”的字节序或进制设置无效。")
            if not isinstance(item.get("signed",False),bool): raise ValueError(f"字段“{name}”的有符号设置无效。")
            color=item.get("color",App._default_wave_color(len(normalized)))
            if not App._valid_wave_color(color): raise ValueError(f"字段“{name}”的颜色设置无效。")
            color=color.upper()
            if color in colors: raise ValueError("不同字段不能使用相同颜色，请修改配置中的字段颜色。")
            colors.add(color)
            names.add(name); used.update(positions)
            normalized.append({"name":name,"length":length,"positions":positions,"endian":endian,
                               "base":base,"signed":item.get("signed",False),"color":color})
        return {"frame_length":frame_size,"header_enabled":header_enabled,"header_hex":header_hex,
                "parse_interval_seconds":interval,"fields":normalized}

    def _apply_config(self,data):
        config=self._validate_config(data)
        if self.parse_running.get(): self.toggle_parse()
        self.frame_len.set(str(config["frame_length"]))
        self.header_enabled.set(config["header_enabled"])
        header_parts=config["header_hex"].split() if config["header_hex"] else []
        self.header_length.set(str(len(header_parts) or 2))
        for index,value in enumerate(self.header_values):
            value.set(header_parts[index] if index<len(header_parts) else "")
        self._header_state()
        self.parse_interval.set(str(config["parse_interval_seconds"]))
        self.fields=config["fields"]
        self._refresh_fields()
        self._parse_pending.clear()
        self._mark_wave_gap()
        self._parse_offset=len(self.rx)
        self._parsed_frames=0
        self._parse_raw_lines=[]; self._parse_value_lines=[]
        self.frame_count.set("已解析 0 帧")
        self.settext(self.raw_frames,"开始持续解析后，完整帧会显示在这里。")
        self.settext(self.parsed,"配置已加载；开始持续解析后显示字段值。")
        self._schedule_wave_redraw(0)

    def _load_config_file(self,path,quiet=False):
        try:
            with open(path,"r",encoding="utf-8") as file:
                self._apply_config(json.load(file))
        except (OSError,json.JSONDecodeError,ValueError) as error:
            if quiet:
                self.status.set(f"默认配置加载失败：{error}")
            else:
                messagebox.showerror("加载配置失败",str(error),parent=self)
            return False
        if not quiet:
            messagebox.showinfo("配置已加载",f"已加载字段配置：\n{path}",parent=self)
        return True

    def load_config(self):
        path=filedialog.askopenfilename(title="加载字段配置",initialdir=str(self.app_dir),
            filetypes=(("UART 配置文件","*.json"),("所有文件","*.*")))
        if path: self._load_config_file(path)

    def save_config(self):
        try: data=self._config_data()
        except (ValueError,TypeError) as error:
            messagebox.showwarning("配置无法保存",str(error),parent=self); return
        path=filedialog.asksaveasfilename(title="保存字段配置",initialdir=str(self.app_dir),
            initialfile="UART字段配置.json",defaultextension=".json",
            filetypes=(("UART 配置文件","*.json"),("所有文件","*.*")))
        if not path: return
        try:
            with open(path,"w",encoding="utf-8") as file:
                json.dump(data,file,ensure_ascii=False,indent=2)
                file.write("\n")
        except OSError as error:
            messagebox.showerror("保存配置失败",str(error),parent=self); return
        messagebox.showinfo("配置已保存",f"字段配置已保存到：\n{path}",parent=self)

    def toggle_parse(self):
        if self.parse_running.get():
            self._mark_wave_gap()
            self.parse_running.set(False)
            self.parse_button.configure(text="开始持续解析")
            if self._parse_after:
                self.after_cancel(self._parse_after); self._parse_after=None
            return
        if not self.port or not getattr(self.port,"is_open",False):
            messagebox.showwarning("串口未连接","请先在串口收发页面连接串口，再开始持续解析。",parent=self)
            return
        try:
            size=self._frame_size()
            header=self._header_bytes()
            if header and len(header)>size: raise ValueError("帧头长度不能大于整帧长度。")
            if any(pos>size for f in self.fields for pos in f["positions"]):
                raise ValueError("已有字段的字节位置超出了当前帧长，请调整帧长或编辑字段。")
            interval=float(self.parse_interval.get())
            if not 0.1<=interval<=60: raise ValueError("解析刷新间隔需在 0.1 到 60 秒之间。")
        except ValueError as e:
            messagebox.showwarning("解析设置无效",str(e)); return
        self._parse_pending.clear()
        self._parse_offset=len(self.rx)
        self._parsed_frames=0
        self._parse_raw_lines=[]; self._parse_value_lines=[]
        self.frame_count.set("已解析 0 帧")
        self.settext(self.raw_frames,"等待完整数据帧……")
        self.settext(self.parsed,"等待完整数据帧……")
        self._schedule_wave_redraw(0)
        self.parse_running.set(True)
        self.parse_button.configure(text="停止持续解析")
        self._schedule_parse(0)

    def _schedule_parse(self, delay=None):
        if not self.parse_running.get(): return
        if delay is None:
            try:
                interval=float(self.parse_interval.get())
                if not 0.1<=interval<=60: raise ValueError()
            except ValueError:
                self.status.set("解析刷新间隔需在 0.1 到 60 秒之间")
                self._mark_wave_gap()
                self.parse_running.set(False)
                self.parse_button.configure(text="开始持续解析")
                return
            delay=max(100,int(interval*1000))
        self._parse_after=self.after(delay,self._parse_tick)

    def _parse_tick(self):
        self._parse_after=None
        if not self.parse_running.get(): return
        new=bytes(self.rx[self._parse_offset:])
        self._parse_offset=len(self.rx)
        self._parse_pending.extend(new)
        try:
            frame_size=self._frame_size()
            header=self._header_bytes()
        except ValueError as e:
            self.status.set(str(e)); self.toggle_parse(); return
        frames=[]
        while True:
            if header:
                pos=self._parse_pending.find(header)
                if pos<0:
                    keep=min(len(self._parse_pending),len(header)-1)
                    if len(self._parse_pending)>keep:
                        del self._parse_pending[:len(self._parse_pending)-keep]
                    break
                if pos: del self._parse_pending[:pos]
            if len(self._parse_pending)<frame_size: break
            frames.append(bytes(self._parse_pending[:frame_size]))
            del self._parse_pending[:frame_size]
        for frame in frames: self._display_frame(frame)
        self._schedule_parse()

    def _display_frame(self,frame):
        self._parsed_frames+=1
        self._parse_raw_lines.append(f"[{self._parsed_frames}] "+" ".join(f"{b:02X}" for b in frame))
        values=[]
        wave_sample={}
        for f in self.fields:
            selected=bytes(frame[pos-1] for pos in sorted(f["positions"]))
            endian="little" if f["endian"]=="小端读取" else "big"
            value=int.from_bytes(selected,endian,signed=f["signed"])
            wave_sample[f["name"]]=value
            fmt={"二进制":"b","八进制":"o","十进制":"d","十六进制":"X"}[f["base"]]
            rendered=format(value,fmt)
            if f["base"]=="十六进制": rendered="0x"+rendered
            values.append(f"{f['name']}={rendered}")
        elapsed=max(0.0,time.monotonic()-self._wave_time_origin) if self._wave_time_origin is not None else 0.0
        self._wave_samples.append({"time":elapsed,"values":wave_sample,
                                   "break_before":self._wave_break_next_sample})
        self._wave_break_next_sample=False
        self._parse_value_lines.append(f"[{self._parsed_frames}]  "+("  |  ".join(values) if values else "（尚未定义字段）"))
        self.frame_count.set(f"已解析 {self._parsed_frames} 帧")
        self.settext(self.raw_frames,"\n".join(self._parse_raw_lines[-2000:]))
        self.settext(self.parsed,"\n".join(self._parse_value_lines[-2000:]))
        self.raw_frames.see("end")
        self.parsed.see("end")
        self._schedule_wave_redraw()

    def _mark_wave_gap(self):
        if self._wave_time_origin is not None:
            self._wave_break_next_sample=True

    @staticmethod
    def settext(box,text):
        box.configure(state="normal")
        box.delete("1.0","end")
        box.insert("1.0",text)
        box.configure(state="disabled")

    def refresh(self):
        if list_ports is None:
            self.ports["values"] = ()
            self.status.set("尚未安装 pyserial")
            return

        previous_device = self.port_map.get(self.portname.get())
        previous_devices=set(self.port_map.values())
        ports = list(list_ports.comports())

        def is_bluetooth(p):
            details = f"{p.description or ''} {p.hwid or ''}".lower()
            return "bthenum" in details or "bluetooth" in details or "蓝牙" in details

        def is_usb_serial(p):
            if is_bluetooth(p):
                return False
            details = f"{p.description or ''} {p.hwid or ''}".lower()
            keywords = ("usb", "uart", "ch340", "ch341", "cp210", "ftdi",
                        "prolific", "pl2303", "silicon labs", "arduino", "stlink")
            return (p.vid is not None and p.pid is not None) or any(word in details for word in keywords)

        labels = []
        self.port_map = {}
        for p in ports:
            description = (p.description or "串口设备").replace(f"({p.device})", "").strip()
            label = f"{p.device} · {description}"
            if is_usb_serial(p):
                label = "★ " + label
            labels.append(label)
            self.port_map[label] = p.device

        values_changed=tuple(self.ports["values"])!=tuple(labels)
        desired_height=max(1,len(labels))
        height_changed=int(self.ports.cget("height"))!=desired_height
        if height_changed:self.ports.configure(height=desired_height)
        if values_changed:
            self.ports["values"] = labels
        preserved = next((label for label in labels if self.port_map[label] == previous_device), None)
        newly_added=next((label for label in labels if self.port_map[label] not in previous_devices),None)
        if preserved:
            if self.portname.get()!=preserved:self.portname.set(preserved)
        elif newly_added and not self.port:
            if self.portname.get()!=newly_added:self.portname.set(newly_added)
        elif labels:
            if self.portname.get()!=labels[0]:self.portname.set(labels[0])
        else:
            if self.portname.get():self.portname.set("")
        if values_changed or height_changed:self._refresh_open_port_dropdown()

        if self.port:
            self.status.set(f"已连接 {self.port.name} @ {self.baud.get()} · RX {len(self.rx)} 字节")
        elif ports:
            self.status.set(f"检测到 {len(ports)} 个串口")
        else:
            self.status.set("未发现串口设备")

    def _auto_refresh_ports(self):
        self.refresh()
        self._port_refresh_after=self.after(350,self._auto_refresh_ports)

    def _refresh_open_port_dropdown(self):
        popdown=f"{self.ports._w}.popdown"
        try:
            if self.tk.call("winfo","exists",popdown) and self.tk.call("winfo","viewable",popdown):
                self.tk.call("ttk::combobox::ConfigureListbox",self.ports._w)
                self.tk.call("update","idletasks")
                self.tk.call("ttk::combobox::PlacePopdown",self.ports._w,popdown)
        except tk.TclError:
            pass
    def connect(self):
        if self.port:
            self._stop_repeat_send()
            self._mark_wave_gap()
            self.stop_reader.set()
            try: self.port.close()
            except Exception: pass
            self.port=None
            self.conn.config(text="连接")
            self.status.set("未连接")
            return
        if serial is None:
            messagebox.showerror("缺少依赖","运行 python -m pip install -r requirements.txt")
            return
        port_name=self.port_map.get(self.portname.get())
        if not port_name:
            messagebox.showwarning("请选择串口","请刷新并选择一个串口设备。")
            return
        try:
            parity={"None":serial.PARITY_NONE,"Even":serial.PARITY_EVEN,"Odd":serial.PARITY_ODD}[self.parity.get()]
            sb={"1":serial.STOPBITS_ONE,"1.5":serial.STOPBITS_ONE_POINT_FIVE,"2":serial.STOPBITS_TWO}[self.stopbits.get()]
            self.port=serial.Serial(port_name,int(self.baud.get()),int(self.bits.get()),parity,sb,timeout=.1,write_timeout=1)
        except Exception as e:
            self.port=None
            messagebox.showerror("连接失败",str(e))
            return
        self.stop_reader.clear()
        self._mark_wave_gap()
        self.reader_thread=threading.Thread(target=self.reader,args=(self.port,),daemon=True)
        self.reader_thread.start()
        self.conn.config(text="断开")
        self.status.set(f"已连接 {port_name} @ {self.baud.get()} · RX 0 字节")

    def reader(self,port):
        while not self.stop_reader.is_set():
            try:
                n=port.in_waiting
                data=port.read(n if n else 1)
                if data: self.q.put(data)
            except Exception as e:
                self.q.put(("error",str(e),port))
                break

    def poll(self):
        changed=False
        batch=bytearray()
        while True:
            try: item=self.q.get_nowait()
            except queue.Empty: break
            if isinstance(item,tuple):
                error_port=item[2] if len(item)>2 else self.port
                if error_port is self.port:
                    self._stop_repeat_send()
                    self._mark_wave_gap()
                    self.status.set("接收错误："+item[1])
                    self.stop_reader.set()
                    try: self.port.close()
                    except Exception: pass
                    self.port=None
                    self.conn.config(text="连接")
            else:
                self.rx.extend(item)
                batch.extend(item)
                if len(self.rx)>262144: del self.rx[:-262144]
                changed=True
        if batch:
            stamp=datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.rx_chunks.append((stamp,bytes(batch),"rx"))
            if len(self.rx_chunks)>5000: del self.rx_chunks[:-5000]
        if changed:
            self.refresh_view()
            if self.port:
                self.status.set(f"已连接 {self.port.name} @ {self.baud.get()} · RX {len(self.rx)} 字节")
        if self.port and self.reader_thread and not self.reader_thread.is_alive():
            self._mark_wave_gap()
            self.status.set("接收线程已停止；请断开后重新连接")
        self.after(50,self.poll)

    def refresh_view(self):
        for widget in (self.out_hex,self.out_text):
            widget.configure(state="normal")
            widget.delete("1.0","end")
        for entry in self.rx_chunks:
            stamp,data,direction=entry if len(entry)==3 else (*entry,"rx")
            hex_payload=" ".join(f"{b:02X}" for b in data)
            text_payload=data.decode("utf-8",errors="replace").replace("\r","\\r").replace("\n","\\n")
            label="发送→" if direction=="tx" else "接收←"
            tags=("tx",) if direction=="tx" else ()
            self.out_hex.insert("end",f"[{stamp}] {label} {hex_payload}\n",tags)
            self.out_text.insert("end",f"[{stamp}] {label} {text_payload}\n",tags)
        for widget in (self.out_hex,self.out_text):
            widget.configure(state="disabled")
        self.out_hex.see("end")
        self.out_text.see("end")

    def clear(self):
        self.rx.clear()
        self.rx_chunks.clear()
        if hasattr(self,"_parse_pending"):
            self._parse_pending.clear()
            self._parse_offset=0
        self.refresh_view()
        self.settext(self.parsed,"接收缓冲已清空。")

    def send(self):
        if not self.port:
            messagebox.showwarning("串口未连接","请先连接串口。")
            return False
        raw=self.sendbox.get("1.0","end-1c")
        try:
            mode=self.sendmode.get()
            if mode=="HEX":
                data=bytes(int(x,16) for x in raw.replace(","," ").replace("，"," ").split())
            elif mode=="数据帧":
                data=self._frame_send_bytes()
            else:
                data=raw.encode("utf-8")
            if self.crlf.get(): data+=b"\r\n"
            if data:
                self.port.write(data)
                stamp=datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self.rx_chunks.append((stamp,data,"tx"))
                if len(self.rx_chunks)>5000: del self.rx_chunks[:-5000]
                self.refresh_view()
                self.status.set(f"已发送 {len(data)} 字节 · RX {len(self.rx)} 字节")
                return True
            messagebox.showwarning("发送内容为空","请先输入要发送的内容。")
            return False
        except ValueError as e:
            if self.sendmode.get()=="数据帧":
                messagebox.showerror("数据帧无效",str(e),parent=self)
            else:
                messagebox.showerror("HEX格式错误",f"请用空格分隔字节，例如 03 E8\n{e}")
            return False
        except Exception as e:
            messagebox.showerror("发送失败",str(e))
            return False

    def _toggle_repeat_send(self):
        if not self.repeat_send.get():
            self._stop_repeat_send()
            return
        if not self.port or not getattr(self.port,"is_open",False):
            self.repeat_send.set(False)
            messagebox.showwarning("串口未连接","请先连接串口，再开启循环发送。",parent=self)
            return
        try:
            interval=float(self.repeat_interval.get())
            if not 0.1<=interval<=3600: raise ValueError("循环发送间隔需在 0.1 到 3600 秒之间。")
        except ValueError as error:
            self.repeat_send.set(False)
            messagebox.showwarning("循环间隔无效",str(error),parent=self)
            return
        if self.send():self._schedule_repeat_send()
        else:self.repeat_send.set(False)

    def _schedule_repeat_send(self):
        if not self.repeat_send.get():return
        try:
            interval=float(self.repeat_interval.get())
            if not 0.1<=interval<=3600: raise ValueError()
        except ValueError:
            self._stop_repeat_send()
            messagebox.showwarning("循环间隔无效","循环发送间隔需在 0.1 到 3600 秒之间。",parent=self)
            return
        self._send_after=self.after(int(interval*1000),self._repeat_send_tick)

    def _repeat_send_tick(self):
        self._send_after=None
        if not self.repeat_send.get():return
        if not self.port or not getattr(self.port,"is_open",False) or not self.send():
            self._stop_repeat_send()
            return
        self._schedule_repeat_send()

    def _stop_repeat_send(self):
        if self._send_after is not None:
            try:self.after_cancel(self._send_after)
            except tk.TclError:pass
            self._send_after=None
        if hasattr(self,"repeat_send"):
            self.repeat_send.set(False)

    def close(self):
        self._stop_repeat_send()
        if getattr(self,"_port_refresh_after",None) is not None:
            try:self.after_cancel(self._port_refresh_after)
            except tk.TclError:pass
        self.stop_reader.set()
        try:
            if self.port: self.port.close()
        except Exception: pass
        self.destroy()


if __name__=="__main__":
    App().mainloop()






