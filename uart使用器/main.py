import json, queue, threading, tkinter as tk, sys
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UART 收发与数据解析")
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
        self.nav_parse = tk.Button(nav, text="▦  数据解析", command=lambda: self.show_page("parse"),
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
        for i in (1,3,5,7): c.columnconfigure(i,weight=1)
        ttk.Label(c,text="串口").grid(row=0,column=0)
        self.portname=tk.StringVar()
        self.port_map={}
        self.show_all_ports=tk.BooleanVar(value=False)
        self.ports=ttk.Combobox(c,textvariable=self.portname,width=25,state="readonly")
        self.ports.grid(row=0,column=1,sticky="ew",padx=5)
        ttk.Button(c,text="刷新",command=self.refresh).grid(row=0,column=2,padx=(0,10))
        ttk.Checkbutton(c,text="显示全部串口（含蓝牙/虚拟口）",variable=self.show_all_ports,command=self.refresh).grid(row=1,column=0,columnspan=3,sticky="w",pady=(7,0))
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
        self.conn=ttk.Button(c,text="连接",command=self.connect)
        self.conn.grid(row=0,column=11,padx=4)

        panes=ttk.Panedwindow(page,orient="vertical")
        panes.grid(row=1,column=0,sticky="nsew")
        top=ttk.Frame(panes); bottom=ttk.Frame(panes)
        panes.add(top,weight=3); panes.add(bottom,weight=2)
        top.rowconfigure(0,weight=1); top.columnconfigure(0,weight=1)
        rf=ttk.LabelFrame(top,text="接收数据",padding=7)
        rf.grid(row=0,column=0,sticky="nsew")
        rf.rowconfigure(0,weight=1); rf.columnconfigure(0,weight=1)
        self.out=tk.Text(rf,font=("Consolas",11),wrap="word",state="disabled")
        self.out.grid(row=0,column=0,sticky="nsew")
        sb=ttk.Scrollbar(rf,command=self.out.yview)
        sb.grid(row=0,column=1,sticky="ns")
        self.out.configure(yscrollcommand=sb.set)
        controls=ttk.Frame(rf)
        controls.grid(row=1,column=0,columnspan=2,sticky="ew",pady=(6,0))
        self.view=tk.StringVar(value="HEX")
        ttk.Radiobutton(controls,text="HEX",variable=self.view,value="HEX",command=self.refresh_view).pack(side="left")
        ttk.Radiobutton(controls,text="文本",variable=self.view,value="文本",command=self.refresh_view).pack(side="left",padx=6)
        ttk.Button(controls,text="清空接收",command=self.clear).pack(side="right")

        sf=ttk.LabelFrame(bottom,text="发送",padding=7)
        sf.pack(fill="both",expand=True)
        sf.columnconfigure(0,weight=1)
        self.sendbox=tk.Text(sf,height=4,font=("Consolas",10),wrap="word")
        self.sendbox.grid(row=0,column=0,sticky="nsew")
        sf.rowconfigure(0,weight=1)
        send_controls=ttk.Frame(sf)
        send_controls.grid(row=1,column=0,sticky="ew",pady=(6,0))
        self.sendmode=tk.StringVar(value="文本")
        ttk.Radiobutton(send_controls,text="文本发送",variable=self.sendmode,value="文本").pack(side="left")
        ttk.Radiobutton(send_controls,text="HEX发送",variable=self.sendmode,value="HEX").pack(side="left",padx=8)
        self.crlf=tk.BooleanVar(value=False)
        ttk.Checkbutton(send_controls,text="追加换行 CRLF",variable=self.crlf).pack(side="left",padx=8)
        ttk.Button(send_controls,text="发送",command=self.send).pack(side="right")

        def set_initial_split():
            pane_height=panes.winfo_height()
            if pane_height>0:
                panes.sashpos(0,int(pane_height*0.60))
        page.after(250,set_initial_split)

    def build_parse_page(self, page):
        page.columnconfigure(0,weight=1)
        page.rowconfigure(1,weight=1)
        cfg=ttk.LabelFrame(page,text="帧设置",padding=8)
        cfg.grid(row=0,column=0,sticky="ew",pady=(0,7))
        cfg.columnconfigure(1,weight=1)

        frame_group=ttk.LabelFrame(cfg,text="数据帧",padding=7)
        frame_group.grid(row=0,column=0,sticky="nsw",padx=(0,8))
        ttk.Label(frame_group,text="帧长（字节，含帧头）").grid(row=0,column=0,sticky="w")
        self.frame_len=tk.StringVar(value="7")
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

        panes=ttk.Panedwindow(page,orient="vertical")
        panes.grid(row=1,column=0,sticky="nsew")
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
        def set_initial_parse_split():
            height=panes.winfo_height()
            if height>0:
                panes.sashpos(0,int(height*0.34))
        page.after(300,set_initial_parse_split)
        ttk.Label(page,text="长时间没有解析结果？请检查帧长、帧头检测是否开启，以及帧头内容是否准确。",
                  foreground="#657487",anchor="w").grid(row=2,column=0,sticky="ew",pady=(5,0))
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
        self.field_tree.delete(*self.field_tree.get_children())
        for i,f in enumerate(self.fields):
            positions="、".join(map(str,f["positions"]))
            endian=f["endian"] if f["length"]>1 else "—"
            self.field_tree.insert("","end",iid=str(i),values=(f["name"],f["length"],positions,endian,f["base"]))

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
        field=self._selected_positions(n,self.fields[i])
        if field:
            if any(j!=i and f["name"]==field["name"] for j,f in enumerate(self.fields)):
                messagebox.showwarning("字段名重复","请使用不同的字段名。"); return
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
                "endian":field["endian"],"base":field["base"],"signed":bool(field["signed"])
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
        normalized=[]; used=set(); names=set()
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
            names.add(name); used.update(positions)
            normalized.append({"name":name,"length":length,"positions":positions,"endian":endian,"base":base,"signed":item.get("signed",False)})
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
        self._parse_offset=len(self.rx)
        self._parsed_frames=0
        self._parse_raw_lines=[]; self._parse_value_lines=[]
        self.frame_count.set("已解析 0 帧")
        self.settext(self.raw_frames,"开始持续解析后，完整帧会显示在这里。")
        self.settext(self.parsed,"配置已加载；开始持续解析后显示字段值。")

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
        for f in self.fields:
            selected=bytes(frame[pos-1] for pos in sorted(f["positions"]))
            endian="little" if f["endian"]=="小端读取" else "big"
            value=int.from_bytes(selected,endian,signed=f["signed"])
            fmt={"二进制":"b","八进制":"o","十进制":"d","十六进制":"X"}[f["base"]]
            rendered=format(value,fmt)
            if f["base"]=="十六进制": rendered="0x"+rendered
            values.append(f"{f['name']}={rendered}")
        self._parse_value_lines.append(f"[{self._parsed_frames}]  "+("  |  ".join(values) if values else "（尚未定义字段）"))
        self.frame_count.set(f"已解析 {self._parsed_frames} 帧")
        self.settext(self.raw_frames,"\n".join(self._parse_raw_lines[-2000:]))
        self.settext(self.parsed,"\n".join(self._parse_value_lines[-2000:]))
        self.raw_frames.see("end")
        self.parsed.see("end")

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

        recommended = [p for p in ports if is_usb_serial(p)]
        fallback_all = not self.show_all_ports.get() and not recommended and bool(ports)
        shown = ports if self.show_all_ports.get() or fallback_all else recommended

        labels = []
        self.port_map = {}
        for p in shown:
            description = (p.description or "串口设备").replace(f"({p.device})", "").strip()
            label = f"{p.device} · {description}"
            if is_usb_serial(p):
                label = "★ " + label
            labels.append(label)
            self.port_map[label] = p.device

        self.ports["values"] = labels
        preserved = next((label for label in labels if self.port_map[label] == previous_device), None)
        if preserved:
            self.portname.set(preserved)
        elif labels:
            self.portname.set(labels[0])
        else:
            self.portname.set("")

        if fallback_all:
            self.status.set("未识别到 USB 串口，临时显示全部串口")
        elif self.show_all_ports.get():
            self.status.set(f"显示全部 {len(ports)} 个串口")
        elif recommended:
            self.status.set(f"已筛出 {len(recommended)} 个 USB 串口设备")
        elif not self.port:
            self.status.set("未发现串口设备")
    def connect(self):
        if self.port:
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
            self.rx_chunks.append((stamp,bytes(batch)))
            if len(self.rx_chunks)>5000: del self.rx_chunks[:-5000]
        if changed:
            self.refresh_view()
            if self.port:
                self.status.set(f"已连接 {self.port.name} @ {self.baud.get()} · RX {len(self.rx)} 字节")
        if self.port and self.reader_thread and not self.reader_thread.is_alive():
            self.status.set("接收线程已停止；请断开后重新连接")
        self.after(50,self.poll)

    def refresh_view(self):
        rows=[]
        for stamp,data in self.rx_chunks:
            if self.view.get()=="HEX":
                payload=" ".join(f"{b:02X}" for b in data)
            else:
                payload=data.decode("utf-8",errors="replace").replace("\r","\\r").replace("\n","\\n")
            rows.append(f"[{stamp}] 接收← {payload}")
        text="\n".join(rows)
        self.settext(self.out,text)
        self.out.see("end")

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
            return
        raw=self.sendbox.get("1.0","end-1c")
        try:
            data=(bytes(int(x,16) for x in raw.replace(","," ").replace("，"," ").split())
                  if self.sendmode.get()=="HEX" else raw.encode("utf-8"))
            if self.crlf.get(): data+=b"\r\n"
            if data:
                self.port.write(data)
                self.status.set(f"已发送 {len(data)} 字节 · RX {len(self.rx)} 字节")
        except ValueError as e:
            messagebox.showerror("HEX格式错误",f"请用空格分隔字节，例如 03 E8\n{e}")
        except Exception as e:
            messagebox.showerror("发送失败",str(e))

    def close(self):
        self.stop_reader.set()
        try:
            if self.port: self.port.close()
        except Exception: pass
        self.destroy()


if __name__=="__main__":
    App().mainloop()






