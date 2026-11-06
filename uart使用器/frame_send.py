import tkinter as tk
from tkinter import ttk


class FrameSendMixin:
    def _build_frame_send_editor(self,parent):
        parent.columnconfigure(0,weight=1)
        parent.rowconfigure(1,weight=1)
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

        scroll_area=ttk.Frame(parent)
        scroll_area.grid(row=1,column=0,sticky="nsew")
        scroll_area.columnconfigure(0,weight=1); scroll_area.rowconfigure(0,weight=1)
        self._frame_send_canvas=tk.Canvas(scroll_area,highlightthickness=0,borderwidth=0)
        self._frame_send_canvas.grid(row=0,column=0,sticky="nsew")
        self._frame_send_layout_after=None
        self._frame_send_layout_signature=None
        self._frame_send_layout_dirty=True
        self._frame_send_scrollregion=None
        self._frame_send_canvas_item_width=0
        frame_send_scroll=ttk.Scrollbar(scroll_area,orient="vertical",command=self._frame_send_canvas.yview)
        frame_send_scroll.grid(row=0,column=1,sticky="ns")
        self._frame_send_canvas.configure(yscrollcommand=frame_send_scroll.set)
        self._frame_send_content=ttk.Frame(self._frame_send_canvas)
        self._frame_send_content.columnconfigure(0,weight=1)
        self._frame_send_content_window=self._frame_send_canvas.create_window(
            (0,0),window=self._frame_send_content,anchor="nw")
        self._frame_send_content.bind("<Configure>",self._update_frame_send_scrollregion)
        self._frame_send_canvas.bind("<Configure>",self._resize_frame_send_canvas)
        self.bind_all("<MouseWheel>",self._frame_send_mousewheel,add="+")

        self._frame_send_values_box=ttk.Frame(self._frame_send_content,padding=(5,1))
        self._frame_send_values_box.columnconfigure(0,weight=1)
        self._frame_send_inputs=ttk.Frame(self._frame_send_values_box)
        self._frame_send_inputs.grid(row=0,column=0,sticky="ew")
        self._frame_send_decimal_cards=[]

        self._frame_send_preview_box=ttk.Frame(self._frame_send_content,padding=(5,1))
        ttk.Label(self._frame_send_preview_box,text="HEX 发送数据").pack(anchor="w")
        self._frame_send_preview=ttk.Frame(self._frame_send_preview_box)
        self._frame_send_preview.pack(fill="x",expand=True)
        self._frame_send_hex_cells=[]
        self._rebuild_frame_send_cells()
        self._toggle_frame_decimal()
        parent.grid(row=0,column=0,sticky="nsew")
        parent.grid_remove()

    def _update_frame_send_scrollregion(self,_event=None):
        if hasattr(self,"_frame_send_canvas"):
            region=self._frame_send_canvas.bbox("all")
            if region!=self._frame_send_scrollregion:
                self._frame_send_canvas.configure(scrollregion=region)
                self._frame_send_scrollregion=region

    def _resize_frame_send_canvas(self,event):
        if event.width!=self._frame_send_canvas_item_width:
            self._frame_send_canvas.itemconfigure(self._frame_send_content_window,width=event.width)
            self._frame_send_canvas_item_width=event.width
        self._schedule_frame_send_layout()

    def _schedule_frame_send_layout(self):
        if not hasattr(self,"_frame_send_canvas"):return
        if self._frame_send_layout_after is not None:
            try:self.after_cancel(self._frame_send_layout_after)
            except tk.TclError:pass
        self._frame_send_layout_after=self.after(70,self._apply_frame_send_layout)

    def _apply_frame_send_layout(self):
        self._frame_send_layout_after=None
        if not self._frame_send_canvas.winfo_exists():return
        self._layout_frame_send_cells()
        self._update_frame_send_scrollregion()

    def _layout_frame_send_cells(self,available_width=None):
        if not hasattr(self,"_frame_send_canvas"):return
        if available_width is None:available_width=self._frame_send_canvas.winfo_width()
        if available_width<=1:return
        available_width=max(1,available_width-8)

        cards=self._frame_send_decimal_cards
        cells=self._frame_send_hex_cells
        if self._frame_send_layout_dirty:
            self._frame_send_card_width=max((card.winfo_reqwidth() for card in cards),default=0)
            self._frame_send_hex_cell_width=max((cell.winfo_reqwidth() for cell in cells),default=0)+2
            self._frame_send_layout_dirty=False
        card_width=self._frame_send_card_width
        card_columns=max(1,(available_width+10)//(card_width+10)) if cards and card_width else 1
        hex_columns=max(1,min(len(cells),available_width//self._frame_send_hex_cell_width)) if cells and self._frame_send_hex_cell_width else 1
        signature=(len(cards),card_columns,len(cells),hex_columns)
        if signature==self._frame_send_layout_signature:return

        if cards and (self._frame_send_layout_signature is None or signature[:2]!=self._frame_send_layout_signature[:2]):
            for card in cards:card.grid_forget()
            for column in range(card_columns):self._frame_send_inputs.columnconfigure(column,weight=0,uniform="decimalfields")
            for index,card in enumerate(cards):
                row,column=divmod(index,card_columns)
                card.grid(row=row,column=column,sticky="w",padx=(2,8),pady=2)

        if cells and (self._frame_send_layout_signature is None or signature[2:]!=self._frame_send_layout_signature[2:]):
            for cell in cells:cell.grid_forget()
            for column in range(hex_columns):self._frame_send_preview.columnconfigure(column,weight=1,uniform="framebytes")
            for index,cell in enumerate(cells):
                row,column=divmod(index,hex_columns)
                cell.grid(row=row,column=column,sticky="ew")
        self._frame_send_layout_signature=signature

    def _frame_send_mousewheel(self,event):
        if self.sendmode.get()!="数据帧" or not self.frame_send_panel.winfo_ismapped():return
        canvas=self._frame_send_canvas
        left,top=canvas.winfo_rootx(),canvas.winfo_rooty()
        if not (left<=event.x_root<left+canvas.winfo_width() and top<=event.y_root<top+canvas.winfo_height()):return
        if event.delta:
            canvas.yview_scroll(-1 if event.delta>0 else 1,"units")
            return "break"

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
        self._frame_send_decimal_cards=[]; self._frame_send_hex_cells=[]
        self._frame_send_layout_dirty=True
        self._frame_send_layout_signature=None
        self._frame_send_hex_vars=[]; self._frame_send_hex_entries=[]
        validate_decimal=(self.register(self._valid_decimal_byte),"%P")
        for index,field in enumerate(self._frame_send_fields):
            card=tk.Frame(self._frame_send_inputs,background="#D8E0E8",padx=1,pady=1)
            self._frame_send_decimal_cards.append(card)
            cell=ttk.Frame(card,padding=(5,3))
            cell.pack()
            value_var=tk.StringVar(value=field["value"])
            ttk.Label(cell,text=f"数值 {index+1}").grid(row=0,column=0,sticky="w",padx=(0,3),pady=1)
            ttk.Entry(cell,textvariable=value_var,width=8,justify="center",validate="key",
                      validatecommand=validate_decimal).grid(row=0,column=1,sticky="w",padx=(0,5),pady=1)
            ttk.Label(cell,text="目标位").grid(row=0,column=2,sticky="w",padx=(0,2),pady=1)
            target_label=tk.StringVar(value=self._target_positions_text(field["positions"]))
            target_box=tk.Menubutton(cell,textvariable=target_label,direction="below",width=8,
                font=("Microsoft YaHei UI",9),bg="#EAF3FB",fg="#245B7A",
                activebackground="#D8EAF7",activeforeground="#174968",
                relief="raised",bd=1,indicatoron=True,anchor="w",padx=5,
                cursor="hand2",highlightthickness=0)
            target_box.grid(row=0,column=3,sticky="w",padx=(0,4),pady=1)
            target_box.bind("<Enter>",lambda event,f=field:self._schedule_target_tooltip(event,f))
            target_box.bind("<Leave>",self._hide_target_tooltip)
            ttk.Button(cell,text="×",width=2,command=lambda i=index:self._remove_frame_send_field(i)).grid(row=0,column=4,pady=1)
            field["value_var"]=value_var; field["target_label_var"]=target_label; field["target_box"]=target_box
            field["position_vars"]={}
            value_var.trace_add("write",lambda *_args,i=index:self._on_frame_send_field_edited(i))
            self._render_frame_send_selector(index)

        validate_hex=(self.register(self._valid_hex_byte),"%P")
        for index in range(size):
            cell=ttk.Frame(self._frame_send_preview,padding=(1,1))
            self._frame_send_hex_cells.append(cell)
            hex_var=tk.StringVar(value=self._frame_send_manual_values[index])
            hex_var.trace_add("write",lambda *_args,i=index:self._on_frame_manual_hex_edited(i))
            hex_entry=tk.Entry(cell,textvariable=hex_var,width=4,justify="center",validate="key",
                validatecommand=validate_hex,bg="#FFFFFF",disabledbackground="#E2E5E9",disabledforeground="#6B7280")
            hex_entry.pack(); hex_entry.bind("<FocusOut>",lambda _event,i=index:self._normalize_manual_hex(i))
            self._frame_send_hex_vars.append(hex_var); self._frame_send_hex_entries.append(hex_entry)
        self._schedule_frame_send_layout()
        self._update_frame_send_preview()

    def _sync_frame_send_fields(self):
        for field in self._frame_send_fields:
            if "value_var" in field:
                field["value"]=field["value_var"].get()
                position_vars=field.get("position_vars",{})
                field["positions"]=[p for p,var in position_vars.items() if var.get()]

    @staticmethod
    def _target_positions_text(positions):
        return f"已选 {len(positions)} 位" if positions else "选择字节位"

    def _schedule_target_tooltip(self,event,field):
        self._hide_target_tooltip()
        detail=("当前选择："+"、".join(f"第 {p} 位" for p in sorted(field.get("positions",[])))) if field.get("positions") else "当前未选择目标位"
        self._target_tooltip_after=self.after(450,lambda:self._show_target_tooltip(event,detail))

    def _show_target_tooltip(self,event,detail):
        self._target_tooltip_after=None
        tip=tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost",True)
        tk.Label(tip,text=detail,bg="#263746",fg="#FFFFFF",
            font=("Microsoft YaHei UI",9),padx=8,pady=5).pack()
        tip.geometry(f"+{event.x_root+12}+{event.y_root+18}")
        self._target_tooltip_window=tip

    def _hide_target_tooltip(self,_event=None):
        after_id=getattr(self,"_target_tooltip_after",None)
        if after_id is not None:
            try:self.after_cancel(after_id)
            except tk.TclError:pass
            self._target_tooltip_after=None
        tip=getattr(self,"_target_tooltip_window",None)
        if tip is not None:
            try:
                if tip.winfo_exists():tip.destroy()
            except tk.TclError:pass
            self._target_tooltip_window=None

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
            menu.add_checkbutton(label=f"第 {position} 位",variable=var,
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
            self._frame_send_values_box.grid(row=0,column=0,sticky="ew",pady=(0,4))
            self._frame_send_preview_box.grid(row=1,column=0,sticky="ew")
        else:
            self._frame_send_values_box.grid_remove()
            self._frame_send_preview_box.grid(row=0,column=0,sticky="ew")
        self._update_frame_send_preview()

    def _set_send_mode(self):
        mode=self.sendmode.get()
        if mode!="文本":
            self.crlf.set(False)
        self.crlf_check.configure(state="normal" if mode=="文本" else "disabled")
        if mode=="数据帧":
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
        self.refresh_view(full=True)
