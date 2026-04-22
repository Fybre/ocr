function uploader() {
  return {
    file: null,
    dragging: false,
    mode: 'auto',
    outputFormat: 'plain',
    llmProvider: 'auto',
    languages: 'eng',
    loading: false,
    error: null,

    onDrop(event) {
      this.dragging = false;
      const files = event.dataTransfer?.files;
      if (files?.length) this.setFile(files[0]);
    },

    onFileSelected(event) {
      const files = event.target?.files;
      if (files?.length) this.setFile(files[0]);
    },

    setFile(f) {
      const allowedExts = ['pdf', 'jpg', 'jpeg', 'png', 'tiff', 'tif', 'webp', 'bmp'];
      const ext = f.name.split('.').pop()?.toLowerCase();
      if (!allowedExts.includes(ext)) {
        this.error = `Unsupported file type: ${f.name}`;
        return;
      }
      this.file = f;
      this.error = null;
    },

    async submit() {
      if (!this.file) return;
      this.loading = true;
      this.error = null;

      const form = new FormData();
      form.append('file', this.file);
      form.append('mode', this.mode);
      form.append('output_format', this.outputFormat);
      form.append('llm_provider', this.llmProvider);
      form.append('languages', this.languages);

      try {
        const res = await fetch('/upload', {
          method: 'POST',
          body: form,
          redirect: 'follow',
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(err.detail || `HTTP ${res.status}`);
        }

        // Server redirects to /view/{job_id} on success
        window.location.href = res.url;
      } catch (err) {
        this.error = err.message || 'Unexpected error';
        this.loading = false;
      }
    },
  };
}
