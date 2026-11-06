import json
import time
from collections import deque
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


class FrameParseMixin:
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

    def _validate_config(self,data):
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
            color=item.get("color",self._default_wave_color(len(normalized)))
            if not self._valid_wave_color(color): raise ValueError(f"字段“{name}”的颜色设置无效。")
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
