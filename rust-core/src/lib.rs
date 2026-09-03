//! Stable, dependency-light primitives shared by Python providers and future
//! native providers. Heavy model code deliberately stays outside this crate.

use sha2::{Digest, Sha256};

/// Build the canonical cache key used by every transport.
pub fn cache_key(
    input_sha256: &str,
    capability: &str,
    provider: &str,
    model: &str,
    options_json: &str,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"{\"capability\":");
    hasher.update(serde_quote(capability).as_bytes());
    hasher.update(b",\"input\":");
    hasher.update(serde_quote(input_sha256).as_bytes());
    hasher.update(b",\"model\":");
    hasher.update(serde_quote(model).as_bytes());
    hasher.update(b",\"options\":");
    hasher.update(options_json.as_bytes());
    hasher.update(b",\"provider\":");
    hasher.update(serde_quote(provider).as_bytes());
    hasher.update(b"}");
    format!("{:x}", hasher.finalize())
}

fn serde_quote(value: &str) -> String {
    serde_json::to_string(value).expect("serializing a string cannot fail")
}

/// Keep path checks in one place for native workers.
pub fn validate_input(
    size_bytes: u64,
    max_bytes: u64,
    is_regular_file: bool,
) -> Result<(), String> {
    if !is_regular_file {
        return Err("input path is not a regular file".to_string());
    }
    if size_bytes > max_bytes {
        return Err(format!("input exceeds {} bytes", max_bytes));
    }
    Ok(())
}

#[cfg(feature = "python")]
mod python {
    use super::*;
    use pyo3::prelude::*;

    #[pyfunction]
    fn cache_key_py(
        input_sha256: &str,
        capability: &str,
        provider: &str,
        model: &str,
        options_json: &str,
    ) -> String {
        cache_key(input_sha256, capability, provider, model, options_json)
    }

    #[pyfunction]
    fn validate_input_py(size_bytes: u64, max_bytes: u64, is_regular_file: bool) -> PyResult<()> {
        validate_input(size_bytes, max_bytes, is_regular_file)
            .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    #[pymodule]
    fn specialist_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(cache_key_py, m)?)?;
        m.add_function(wrap_pyfunction!(validate_input_py, m)?)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cache_key_is_stable() {
        let first = cache_key("abc", "vision.ocr", "paddleocr", "v1", "{}");
        let second = cache_key("abc", "vision.ocr", "paddleocr", "v1", "{}");
        assert_eq!(first, second);
        assert_eq!(first.len(), 64);
    }

    #[test]
    fn validates_size_and_file_kind() {
        assert!(validate_input(10, 100, true).is_ok());
        assert!(validate_input(101, 100, true).is_err());
        assert!(validate_input(10, 100, false).is_err());
    }
}
