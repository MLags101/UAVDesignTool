import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
from tkinter.messagebox import askyesno
from PIL import Image, ImageTk
import os
import json
import shutil
import datetime
import subprocess

class UAVDesignTool:
    def __init__(self, root):
        self.root = root
        self.root.title("UAV Design Organizer")
        self.root.geometry("800x600")

        self.project_data = {
            "name": "",
            "author": "",
            "summary": "",
            "image": None,
            "stages": {
                "Conceptual": {"parameters": {}, "images": [], "notes": {}, "completed": False, "review_state": False, "parameters_config": [
                    {"name": "Configuration Type", "required": True},
                    {"name": "Wing Type", "required": True},
                    {"name": "Tail Type", "required": True},
                    {"name": "Fuselage Geometry", "required": True},
                    {"name": "Engine Type", "required": True},
                    {"name": "Landing Gear Type", "required": True}
                ]},
                "Preliminary": {"parameters": {}, "images": [], "notes": {}, "completed": False, "review_state": False, "parameters_config": [
                    {"name": "Max Takeoff Weight (W_TO)", "required": True},
                    {"name": "Wing Area (S)", "required": True},
                    {"name": "Engine Thrust/Power (T/P)", "required": True},
                    {"name": "Autopilot Preliminary Data", "required": True}
                ]},
                "Detail": {"parameters": {}, "images": [], "notes": {}, "completed": False, "review_state": False, "parameters_config": [
                    {"name": "Wing Parameters", "required": True},
                    {"name": "Tail Parameters", "required": True},
                    {"name": "Fuselage Parameters", "required": True},
                    {"name": "Landing Gear Parameters", "required": True},
                    {"name": "Engine Parameters", "required": True},
                    {"name": "Autopilot Parameters", "required": True},
                    {"name": "Subsystems Parameters", "required": True}
                ]}
            }
        }
        self.completed_stages = {"Conceptual": False, "Preliminary": False, "Detail": False}
        self.project_dir = None
        self.proj_img_label = None

        self.create_start_page()

    def create_start_page(self):
        self.start_frame = ttk.Frame(self.root)
        self.start_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(self.start_frame, text="Welcome to UAV Design Organizer").pack(pady=10)

        load_btn = tk.Button(self.start_frame, text="Load Project", command=self.load_project)
        load_btn.pack(pady=5)

        new_btn = tk.Button(self.start_frame, text="New Project", command=self.new_project)
        new_btn.pack(pady=5)

    def new_project(self):
        self.project_window = tk.Toplevel(self.root)
        self.project_window.title("New Project")

        tk.Label(self.project_window, text="Project Name:").pack()
        self.name_var = tk.StringVar()
        tk.Entry(self.project_window, textvariable=self.name_var).pack()

        tk.Label(self.project_window, text="Author:").pack()
        self.author_var = tk.StringVar()
        tk.Entry(self.project_window, textvariable=self.author_var).pack()

        tk.Label(self.project_window, text="Summary:").pack()
        self.summary_text = scrolledtext.ScrolledText(self.project_window, height=5)
        self.summary_text.pack()

        tk.Label(self.project_window, text="Optional Image:").pack()
        self.proj_img_path = tk.StringVar()
        tk.Entry(self.project_window, textvariable=self.proj_img_path).pack()
        tk.Button(self.project_window, text="Browse", command=self.browse_proj_img).pack()

        tk.Button(self.project_window, text="Create", command=self.create_project).pack(pady=10)

    def browse_proj_img(self):
        file = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.png *.gif")])
        if file:
            self.proj_img_path.set(file)

    def create_project(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Incomplete", "Project name required.")
            return

        self.project_data["name"] = name
        self.project_data["author"] = self.author_var.get()
        self.project_data["summary"] = self.summary_text.get("1.0", tk.END).strip()
        proj_img = self.proj_img_path.get()
        if proj_img:
            self.project_data["image"] = os.path.basename(proj_img)

        self.project_dir = filedialog.askdirectory(title="Select Project Folder")
        if not self.project_dir:
            return

        self.project_dir = os.path.join(self.project_dir, self.project_data["name"])
        os.makedirs(self.project_dir, exist_ok=True)

        # Copy project image
        if proj_img:
            dst = os.path.join(self.project_dir, self.project_data["image"])
            shutil.copy(proj_img, dst)

        # Create stage directories
        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            os.makedirs(os.path.join(self.project_dir, stagename), exist_ok=True)

        # Save initial JSON
        json_path = os.path.join(self.project_dir, f"{self.project_data['name']}.json")
        with open(json_path, "w") as f:
            json.dump(self.project_data, f)

        self.project_window.destroy()
        self.start_frame.destroy()
        self.setup_main_ui()

    def setup_main_ui(self, is_loaded=False):
        self.root.title(f"UAV Design Organizer - {self.project_data['name']}")
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tabs = {}
        self.create_tabs(is_loaded)

        # Lock tabs initially
        self.notebook.tab(1, state="disabled" if not self.completed_stages["Conceptual"] else "normal")  # Preliminary
        self.notebook.tab(2, state="disabled" if not self.completed_stages["Preliminary"] else "normal")  # Detail

        # Menu for save and config (ADDED IMPORT/EXPORT)
        menubar = tk.Menu(self.root)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Save Project", command=self.save_project)
        
        filemenu.add_separator()
        filemenu.add_command(label="Import Parameter Config", command=self.import_param_config)
        filemenu.add_command(label="Export Parameter Config", command=self.export_param_config)

        menubar.add_cascade(label="File", menu=filemenu)
        self.root.config(menu=menubar)

        # Display project image in lower right
        self.bottom_frame = ttk.Frame(self.root)
        self.bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        if self.project_data["image"]:
            img_path = self.proj_img_path.get() if hasattr(self, 'proj_img_path') else os.path.join(self.project_dir, self.project_data["image"])
            if os.path.exists(img_path):
                img = Image.open(img_path)
                img.thumbnail((100, 100))
                photo = ImageTk.PhotoImage(img)
                self.proj_img_label = tk.Label(self.bottom_frame, image=photo)
                self.proj_img_label.image = photo
                self.proj_img_label.pack(side=tk.RIGHT, anchor=tk.SE)

    def create_tabs(self, is_loaded):
        stages = ["Conceptual Design", "Preliminary Design", "Detail Design"]
        reviews = ["CDR", "PDR", "FDR"]

        for i, stage in enumerate(stages):
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text=stage)
            self.tabs[stage] = tab

            stagename = stage.replace(" Design", "")

            # Parameters
            tk.Label(tab, text="Parameters:").pack(anchor=tk.W)
            param_frame = ttk.Frame(tab)
            param_frame.pack(fill=tk.X)
            self.project_data["stages"][stagename]["param_frame"] = param_frame
            self.refresh_params(stagename)

            configure_btn = tk.Button(tab, text="Configure Parameters", command=lambda s=stagename: self.configure_parameters(s))
            configure_btn.pack()

            # Notes sub-tabs
            tk.Label(tab, text="Notes:").pack(anchor=tk.W)
            notes_notebook = ttk.Notebook(tab)
            notes_notebook.pack(fill=tk.BOTH, expand=True)
            self.project_data["stages"][stagename]["notes_notebook"] = notes_notebook
            if not is_loaded:
                default_name = f"{stagename} Notes"
                self.add_note_tab(stagename, default_name)

            add_note_btn = tk.Button(tab, text="Add Note Tab", command=lambda s=stagename: self.add_note_tab(s))
            add_note_btn.pack()

            # Images
            tk.Label(tab, text="Images:").pack(anchor=tk.W)
            upload_btn = tk.Button(tab, text="Upload Image", command=lambda s=stagename: self.upload_image(s))
            upload_btn.pack()
            view_btn = tk.Button(tab, text="View/Edit Images", command=lambda s=stagename: self.view_images(s))
            view_btn.pack()

            # Design Review
            review_var = tk.BooleanVar()
            tk.Checkbutton(tab, text=f"Conducted {reviews[i]} Review", variable=review_var).pack(anchor=tk.W)
            self.project_data["stages"][stagename]["review_var"] = review_var

            # Complete Stage
            complete_btn = tk.Button(tab, text="Complete Stage", command=lambda s=stage: self.complete_stage(s))
            complete_btn.pack()

        # Documentation tab
        doc_tab = ttk.Frame(self.notebook)
        self.notebook.add(doc_tab, text="Documentation")

        # Project Image change
        tk.Label(doc_tab, text="Project Image:").pack(anchor=tk.W)
        change_img_btn = tk.Button(doc_tab, text="Add/Change Project Image", command=self.change_project_image)
        change_img_btn.pack()

        # Checkboxes for stages
        self.doc_include = {
            "Conceptual": tk.BooleanVar(),
            "Preliminary": tk.BooleanVar(),
            "Detail": tk.BooleanVar()
        }
        for stage in ["Conceptual", "Preliminary", "Detail"]:
            chk = tk.Checkbutton(doc_tab, text=f"Include {stage}", variable=self.doc_include[stage])
            chk.pack(anchor=tk.W)
            if not self.completed_stages[stage]:
                chk.config(state=tk.DISABLED)

        # Customization settings
        self.doc_options = {
            "include_images": tk.BooleanVar(value=True),
            "include_date": tk.BooleanVar(value=True),
            "include_page_numbers": tk.BooleanVar(value=True),
            "compile_pdf": tk.BooleanVar(value=True)
        }
        tk.Checkbutton(doc_tab, text="Include Images", variable=self.doc_options["include_images"]).pack(anchor=tk.W)
        tk.Checkbutton(doc_tab, text="Include Date", variable=self.doc_options["include_date"]).pack(anchor=tk.W)
        tk.Checkbutton(doc_tab, text="Include Page Numbers", variable=self.doc_options["include_page_numbers"]).pack(anchor=tk.W)
        tk.Checkbutton(doc_tab, text="Compile to PDF", variable=self.doc_options["compile_pdf"]).pack(anchor=tk.W)

        # Generate button
        generate_btn = tk.Button(doc_tab, text="Generate", command=self.generate_report)
        generate_btn.pack(pady=10)

    def refresh_params(self, stagename):
        param_frame = self.project_data["stages"][stagename]["param_frame"]
        for child in param_frame.winfo_children():
            child.destroy()

        self.project_data["stages"][stagename]["param_widgets"] = {}
        config = self.project_data["stages"][stagename]["parameters_config"]
        # Also ensure the parameters dictionary is consistent with the config
        # This is important after importing a new config
        current_params = self.project_data["stages"][stagename]["parameters"]
        updated_params = {param["name"]: current_params.get(param["name"], "") for param in config}
        self.project_data["stages"][stagename]["parameters"] = updated_params
        
        for param in config:
            name = param["name"]
            label_text = f"* {name} *" if param["required"] else name
            tk.Label(param_frame, text=label_text + ":").pack(anchor=tk.W)
            # Use the potentially updated parameters value
            var = tk.StringVar(value=self.project_data["stages"][stagename]["parameters"].get(name, ""))
            entry = tk.Entry(param_frame, textvariable=var)
            entry.pack(fill=tk.X)
            self.project_data["stages"][stagename]["param_widgets"][name] = var

    def configure_parameters(self, stagename):
        config_window = tk.Toplevel(self.root)
        config_window.title(f"Configure Parameters for {stagename}")

        listbox = tk.Listbox(config_window)
        listbox.pack(fill=tk.BOTH, expand=True)

        config = self.project_data["stages"][stagename]["parameters_config"]
        for param in config:
            listbox.insert(tk.END, param["name"] + (" (required)" if param["required"] else ""))

        def add_param():
            name = simpledialog.askstring("Add Parameter", "Parameter name:")
            if name:
                required = askyesno("Required", "Is this parameter required?")
                config.append({"name": name, "required": required})
                listbox.insert(tk.END, name + (" (required)" if required else ""))
                if name not in self.project_data["stages"][stagename]["parameters"]:
                    self.project_data["stages"][stagename]["parameters"][name] = ""

        def edit_param():
            selected = listbox.curselection()
            if selected:
                idx = selected[0]
                param = config[idx]
                name = simpledialog.askstring("Edit Parameter", "Parameter name:", initialvalue=param["name"])
                if name:
                    # FIX: Convert boolean default to string 'yes' or 'no' to prevent the Tcl/Tk "bad -default value '1'" error.
                    default_choice = 'yes' if param["required"] else 'no'
                    required = askyesno("Required", "Is this parameter required?", default=default_choice)
                    
                    old_name = param["name"]
                    config[idx] = {"name": name, "required": required}
                    listbox.delete(idx)
                    listbox.insert(idx, name + (" (required)" if required else ""))
                    if old_name != name:
                        if old_name in self.project_data["stages"][stagename]["parameters"]:
                            # Rename the parameter value
                            self.project_data["stages"][stagename]["parameters"][name] = self.project_data["stages"][stagename]["parameters"].pop(old_name)

        def remove_param():
            selected = listbox.curselection()
            if selected:
                idx = selected[0]
                old_name = config[idx]["name"]
                del config[idx]
                listbox.delete(idx)
                if old_name in self.project_data["stages"][stagename]["parameters"]:
                    del self.project_data["stages"][stagename]["parameters"][old_name]

        tk.Button(config_window, text="Add", command=add_param).pack(side=tk.LEFT)
        tk.Button(config_window, text="Edit", command=edit_param).pack(side=tk.LEFT)
        tk.Button(config_window, text="Remove", command=remove_param).pack(side=tk.LEFT)
        tk.Button(config_window, text="Done", command=lambda: [self.refresh_params(stagename), config_window.destroy()]).pack(side=tk.RIGHT)

    def import_param_config(self):
        """Imports the parameter configuration from a JSON file and updates all stages."""
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json")], 
            title="Import Parameter Configuration"
        )
        if not file_path:
            return

        try:
            with open(file_path, 'r') as f:
                config_data = json.load(f)

            stages = ["Conceptual", "Preliminary", "Detail"]
            for stage in stages:
                if stage in config_data:
                    # Replace the existing configuration for the stage
                    self.project_data["stages"][stage]["parameters_config"] = config_data[stage]
                    # The parameters values dictionary needs to be rebuilt or cleaned up 
                    # for the new configuration, which is handled in refresh_params.
                    self.refresh_params(stage)
            
            messagebox.showinfo("Success", "Parameter configuration imported successfully.")

        except Exception as e:
            messagebox.showerror("Import Error", f"Failed to import configuration: {e}")

    def export_param_config(self):
        """Exports the parameter configuration for all stages to a JSON file."""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json", 
            filetypes=[("JSON files", "*.json")], 
            title="Export Parameter Configuration"
        )
        if not file_path:
            return

        config_data = {}
        stages = ["Conceptual", "Preliminary", "Detail"]
        for stage in stages:
            # Collect the current parameters_config for each stage
            config_data[stage] = self.project_data["stages"][stage]["parameters_config"]

        try:
            with open(file_path, 'w') as f:
                json.dump(config_data, f, indent=4)
            messagebox.showinfo("Success", f"Parameter configuration exported successfully to:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export configuration: {e}")

    def change_project_image(self):
        file = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.png *.gif")])
        if file:
            basename = os.path.basename(file)
            dst = os.path.join(self.project_dir, basename)
            shutil.copy(file, dst)
            self.project_data["image"] = basename
            # Update display
            img = Image.open(dst)
            img.thumbnail((100, 100))
            photo = ImageTk.PhotoImage(img)
            self.proj_img_label.config(image=photo)
            self.proj_img_label.image = photo

    def add_note_tab(self, stagename, name=None):
        if not name:
            name = simpledialog.askstring("Note Name", "Enter note name:")
            if not name:
                return
        notes_text = scrolledtext.ScrolledText(self.project_data["stages"][stagename]["notes_notebook"], height=10)
        tab = self.project_data["stages"][stagename]["notes_notebook"].add(notes_text, text=name)
        self.project_data["stages"][stagename]["notes"][name] = {"widget": notes_text, "file": f"{self.project_data['name']}_{stagename}_{name}.md"}

    def upload_image(self, stagename):
        file = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.png *.gif")])
        if file:
            caption = simpledialog.askstring("Caption", "Enter image caption:")
            self.project_data["stages"][stagename]["images"].append({
                "path": file,
                "caption": caption or ""
            })

    def view_images(self, stagename):
        view_window = tk.Toplevel(self.root)
        view_window.title(f"{stagename} Images")

        tree = ttk.Treeview(view_window, columns=("Caption",), show="headings")
        tree.heading("Caption", text="Caption")
        tree.pack(fill=tk.BOTH, expand=True)

        image_frame = ttk.Frame(view_window)
        image_frame.pack(fill=tk.BOTH, expand=True)
        self.image_label = tk.Label(image_frame)
        self.image_label.pack()

        for i, img in enumerate(self.project_data["stages"][stagename]["images"]):
            tree.insert("", tk.END, iid=str(i), values=(img["caption"],))

        def show_image(event):
            selected = tree.selection()
            if selected:
                idx = int(selected[0])
                img_path = self.project_data["stages"][stagename]["images"][idx]["path"]
                try:
                    img = Image.open(img_path)
                    img.thumbnail((400, 400))
                    photo = ImageTk.PhotoImage(img)
                    self.image_label.config(image=photo)
                    self.image_label.image = photo
                except Exception as e:
                    messagebox.showerror("Error", f"Could not load image: {e}")

        tree.bind("<<TreeviewSelect>>", show_image)

        def edit_selected():
            selected = tree.selection()
            if selected:
                idx = int(selected[0])
                img = self.project_data["stages"][stagename]["images"][idx]
                caption = simpledialog.askstring("Edit Caption", "Caption:", initialvalue=img["caption"])
                if caption is not None:
                    img["caption"] = caption
                tree.item(selected, values=(caption, ))

        tk.Button(view_window, text="Edit Selected", command=edit_selected).pack()

    def complete_stage(self, stage):
        stagename = stage.replace(" Design", "")

        config = self.project_data["stages"][stagename]["parameters_config"]
        # Ensure all required parameters are non-empty
        params_filled = all(self.project_data["stages"][stagename]["param_widgets"][param["name"]].get().strip() for param in config if param["required"])
        if not params_filled:
            messagebox.showwarning("Incomplete", "Fill all required parameters.")
            return

        if not self.project_data["stages"][stagename]["review_var"].get():
            messagebox.showwarning("Incomplete", "Conduct the design review.")
            return

        self.completed_stages[stagename] = True
        messagebox.showinfo("Completed", f"{stage} completed!")

        if stagename == "Conceptual":
            self.notebook.tab(1, state="normal")
        elif stagename == "Preliminary":
            self.notebook.tab(2, state="normal")

        # Enable checkbox in Documentation
        for child in self.notebook.nametowidget(self.notebook.tabs()[3]).winfo_children():
            if isinstance(child, tk.Checkbutton) and child.cget("text") == f"Include {stagename}":
                child.config(state=tk.NORMAL)

    def generate_report(self):
        selected_stages = [stage for stage in ["Conceptual", "Preliminary", "Detail"] if self.doc_include[stage].get()]
        if not selected_stages:
            messagebox.showwarning("No Stages", "Select at least one stage.")
            return

        if self.doc_options["compile_pdf"].get() and shutil.which('pdflatex') is None:
            messagebox.showerror("LaTeX Not Found", "pdflatex is not installed or not in your PATH. Please install MiKTeX or TeX Live, and ensure pdflatex is accessible from the command line.")
            return

        include_images = self.doc_options["include_images"].get()
        include_date = self.doc_options["include_date"].get()
        include_page_numbers = self.doc_options["include_page_numbers"].get()

        date_str = datetime.date.today().strftime("%B %d, %Y") if include_date else ""

        # Handle unsaved images by copying to project dir
        all_images = []
        for stage in selected_stages:
            for img in self.project_data["stages"][stage]["images"]:
                if os.path.isabs(img["path"]):
                    basename = os.path.basename(img["path"])
                    dst = os.path.join(self.project_dir, stage, basename)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy(img["path"], dst)
                    img["path"] = basename
                all_images.append((stage, img))

        # Handle project image
        if self.project_data["image"] and include_images:
            img_path = os.path.join(self.project_dir, self.project_data["image"])
            if not os.path.exists(img_path):
                if hasattr(self, 'proj_img_path') and os.path.exists(self.proj_img_path.get()):
                    shutil.copy(self.proj_img_path.get(), img_path)

        # Generate LaTeX
        tex_content = r"""
\documentclass{article}
\usepackage{graphicx}
\usepackage{amsmath}
\usepackage[margin=1in]{geometry}
"""
        if not include_page_numbers:
            tex_content += r"\pagestyle{empty}" + "\n"

        tex_content += r"\begin{document}" + "\n"

        tex_content += r"\begin{titlepage}" + "\n"
        tex_content += r"\vspace*{\fill}" + "\n"
        tex_content += r"\begin{center}" + "\n"
        tex_content += r"{\huge " + self.project_data["name"].replace("\n", "\\\\") + r" \par}" + "\n"
        tex_content += r"\vspace{1cm}" + "\n"
        tex_content += r"{\Large " + self.project_data["author"].replace("\n", "\\\\") + r" \par}" + "\n"
        if include_date:
            tex_content += r"\vspace{1cm}" + "\n"
            tex_content += r"{\large " + date_str + r" \par}" + "\n"
        tex_content += r"\end{center}" + "\n"
        tex_content += r"\vspace*{\fill}" + "\n"
        tex_content += r"\end{titlepage}" + "\n"

        tex_content += r"\section{Abstract}" + "\n"
        tex_content += self.project_data["summary"].replace("\n", "\\\\") + r"\\" + "\n"

        if self.project_data["image"] and include_images and os.path.exists(os.path.join(self.project_dir, self.project_data["image"])):
            tex_content += r"\begin{center}" + "\n"
            tex_content += r"\includegraphics[width=0.5\textwidth]{" + self.project_data["image"] + r"}" + "\n"
            tex_content += r"\end{center}" + "\n"

        for stage in selected_stages:
            tex_content += r"\section{" + stage + r" Design}" + "\n"

            tex_content += r"\subsection{Parameters}" + "\n"
            tex_content += r"\begin{itemize}" + "\n"
            for param in self.project_data["stages"][stage]["parameters_config"]:
                name = param["name"]
                value = self.project_data["stages"][stage]["param_widgets"][name].get().replace("\n", "\\\\")
                if not param["required"] and not value.strip():
                    continue
                tex_content += r"\item \textbf{" + name.replace("\n", "\\\\") + r":} " + value + "\n"
            tex_content += r"\end{itemize}" + "\n"

            tex_content += r"\subsection{Notes}" + "\n"
            for name, note in self.project_data["stages"][stage]["notes"].items():
                note_text = note["widget"].get("1.0", tk.END).strip().replace("\n", "\\\\")
                tex_content += r"\subsubsection{" + name.replace("\n", "\\\\") + r"}" + "\n" + note_text + r"\\" + "\n"

        if include_images and all_images:
            tex_content += r"\section{Figures}" + "\n"
            for i, (stage, img) in enumerate(all_images, 1):
                caption = img["caption"].replace("\n", "\\\\")
                tex_content += r"\begin{figure}[h]" + "\n"
                tex_content += r"\centering" + "\n"
                tex_content += r"\includegraphics[width=0.5\textwidth]{" + stage + "/" + img["path"] + r"}" + "\n"
                tex_content += r"\caption{" + caption + r"}" + "\n"
                tex_content += r"\end{figure}" + "\n"
        
        tex_content += r"\end{document}"

        tex_path = os.path.join(self.project_dir, "report.tex")
        with open(tex_path, "w") as f:
            f.write(tex_content)

        if self.doc_options["compile_pdf"].get():
            # Compile to PDF
            try:
                subprocess.call(['pdflatex', '-interaction=nonstopmode', tex_path], cwd=self.project_dir)
                messagebox.showinfo("Generated", "Report PDF generated at " + os.path.join(self.project_dir, "report.pdf"))
            except Exception as e:
                messagebox.showerror("Error", f"Failed to compile PDF: {e}")
        else:
            messagebox.showinfo("Generated", "LaTeX file generated at " + tex_path)

    def save_project(self):
        # Assume project_dir is always set after creation or load
        if not self.project_dir:
            messagebox.showwarning("No Directory", "Project directory not set.")
            return

        # Temp store non-serializable
        temp_data = {}
        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            self.project_data["stages"][stagename]["completed"] = self.completed_stages[stagename]
            self.project_data["stages"][stagename]["review_state"] = self.project_data["stages"][stagename]["review_var"].get()
            temp_data[stagename] = {
                "param_widgets": self.project_data["stages"][stagename].pop("param_widgets", None),
                "notes_notebook": self.project_data["stages"][stagename].pop("notes_notebook", None),
                "review_var": self.project_data["stages"][stagename].pop("review_var", None),
                "param_frame": self.project_data["stages"][stagename].pop("param_frame", None),
                "notes_widgets": {name: note.pop("widget", None) for name, note in self.project_data["stages"][stagename]["notes"].items()}
            }

        # Copy project image if changed (but since no change UI, skip or check)
        if self.project_data["image"]:
            src = self.proj_img_path.get() if hasattr(self, 'proj_img_path') and self.proj_img_path.get() else ""
            if src and os.path.exists(src):
                dst = os.path.join(self.project_dir, self.project_data["image"])
                shutil.copy(src, dst)

        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            stage_dir = os.path.join(self.project_dir, stagename)
            os.makedirs(stage_dir, exist_ok=True)

            # Save notes to MD
            for name, note in self.project_data["stages"][stagename]["notes"].items():
                md_path = os.path.join(stage_dir, note["file"])
                with open(md_path, "w") as f:
                    f.write(temp_data[stagename]["notes_widgets"][name].get("1.0", tk.END))

            # Copy images and update paths
            for img in self.project_data["stages"][stagename]["images"]:
                basename = os.path.basename(img["path"])
                dst = os.path.join(stage_dir, basename)
                if os.path.exists(img["path"]):
                    shutil.copy(img["path"], dst)
                img["path"] = basename  # Relative path for JSON

            # Sync parameters
            for param in self.project_data["stages"][stagename]["parameters_config"]:
                name = param["name"]
                self.project_data["stages"][stagename]["parameters"][name] = temp_data[stagename]["param_widgets"][name].get()

        json_path = os.path.join(self.project_dir, f"{self.project_data['name']}.json")
        with open(json_path, "w") as f:
            json.dump(self.project_data, f)

        # Restore temp
        for stagename in temp_data:
            self.project_data["stages"][stagename]["param_widgets"] = temp_data[stagename]["param_widgets"]
            self.project_data["stages"][stagename]["notes_notebook"] = temp_data[stagename]["notes_notebook"]
            self.project_data["stages"][stagename]["review_var"] = temp_data[stagename]["review_var"]
            self.project_data["stages"][stagename]["param_frame"] = temp_data[stagename]["param_frame"]
            for name, widget in temp_data[stagename]["notes_widgets"].items():
                self.project_data["stages"][stagename]["notes"][name]["widget"] = widget

        messagebox.showinfo("Saved", "Project saved successfully.")

    def load_project(self):
        json_file = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if not json_file:
            return

        self.project_dir = os.path.dirname(json_file)

        with open(json_file, "r") as f:
            self.project_data = json.load(f)

        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            self.completed_stages[stagename] = self.project_data["stages"][stagename].get("completed", False)

        self.start_frame.destroy()
        self.setup_main_ui(is_loaded=True)

        # Reload stages
        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            # Parameters
            self.refresh_params(stagename)

            # Notes
            for name, note in self.project_data["stages"][stagename]["notes"].items():
                notes_text = scrolledtext.ScrolledText(self.project_data["stages"][stagename]["notes_notebook"], height=10)
                md_path = os.path.join(self.project_dir, stagename, note["file"])
                if os.path.exists(md_path):
                    with open(md_path, "r") as f:
                        notes_text.insert(tk.END, f.read())
                self.project_data["stages"][stagename]["notes_notebook"].add(notes_text, text=name)
                note["widget"] = notes_text

            # Images (paths are relative)
            for img in self.project_data["stages"][stagename]["images"]:
                img["path"] = os.path.join(self.project_dir, stagename, img["path"])

            # Review state
            self.project_data["stages"][stagename]["review_var"].set(self.project_data["stages"][stagename].get("review_state", False))

            # Enable doc checkboxes if completed
            if self.completed_stages[stagename]:
                for child in self.notebook.nametowidget(self.notebook.tabs()[3]).winfo_children():
                    if isinstance(child, tk.Checkbutton) and child.cget("text") == f"Include {stagename}":
                        child.config(state=tk.NORMAL)

if __name__ == "__main__":
    root = tk.Tk()
    app = UAVDesignTool(root)
    root.mainloop()