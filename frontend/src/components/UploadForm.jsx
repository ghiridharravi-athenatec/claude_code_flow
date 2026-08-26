import { useState } from "react";

const ACCEPTED_EXTENSIONS = ".pdf,.txt,.docx";

function UploadForm({ onSubmit, isSubmitting }) {
  const [selectedFile, setSelectedFile] = useState(null);

  function handleFileChange(event) {
    const file = event.target.files[0] || null;
    setSelectedFile(file);
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (selectedFile) {
      onSubmit(selectedFile);
    }
  }

  return (
    <form className="upload-form" onSubmit={handleSubmit}>
      <label htmlFor="record-file">Medical record (PDF, TXT, or DOCX, up to 10 MB)</label>
      <input
        id="record-file"
        type="file"
        accept={ACCEPTED_EXTENSIONS}
        onChange={handleFileChange}
        disabled={isSubmitting}
      />
      <button type="submit" disabled={!selectedFile || isSubmitting}>
        {isSubmitting ? "Validating..." : "Validate Record"}
      </button>
    </form>
  );
}

export default UploadForm;
