//! Bounded, duplicate-safe JSON and RFC 8785 for CW evidence only.
//! Shared proof-core canonicalization and existing token contracts are unchanged.
use serde::de::{DeserializeSeed, Error, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};
use sha2::{Digest, Sha256};
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::path::Path;

pub const MAX_ARTIFACT: usize = 262_144;
pub const MAX_BUNDLE: usize = 2 * 1024 * 1024;
const MAX_SAFE: f64 = 9_007_199_254_740_991.;

pub fn read(path: &Path, limit: usize) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(|e| format!("input_read_failed:{e}"))?
        .take((limit + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|e| format!("input_read_failed:{e}"))?;
    if bytes.is_empty() || bytes.len() > limit {
        return Err("empty_or_oversized_input".into());
    }
    Ok(bytes)
}

struct Seed<'a> {
    nodes: &'a mut usize,
    depth: usize,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = Value;
    fn deserialize<D: serde::Deserializer<'de>>(self, de: D) -> Result<Value, D::Error> {
        *self.nodes += 1;
        if self.depth > 32 || *self.nodes > 50_000 {
            return Err(D::Error::custom("json_depth_or_node_bound"));
        }
        de.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Seed<'_> {
    type Value = Value;
    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("bounded JSON")
    }
    fn visit_bool<E: Error>(self, v: bool) -> Result<Value, E> {
        Ok(Value::Bool(v))
    }
    fn visit_unit<E: Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_none<E: Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_i64<E: Error>(self, v: i64) -> Result<Value, E> {
        if v.unsigned_abs() > MAX_SAFE as u64 {
            return Err(E::custom("unsafe_integer"));
        }
        Ok(v.into())
    }
    fn visit_u64<E: Error>(self, v: u64) -> Result<Value, E> {
        if v > MAX_SAFE as u64 {
            return Err(E::custom("unsafe_integer"));
        }
        Ok(v.into())
    }
    fn visit_f64<E: Error>(self, v: f64) -> Result<Value, E> {
        if !v.is_finite() || (v.fract() == 0. && v.abs() > MAX_SAFE) {
            return Err(E::custom("nonfinite_or_unsafe_number"));
        }
        Number::from_f64(v)
            .map(Value::Number)
            .ok_or_else(|| E::custom("nonfinite_number"))
    }
    fn visit_str<E: Error>(self, v: &str) -> Result<Value, E> {
        Ok(v.into())
    }
    fn visit_string<E: Error>(self, v: String) -> Result<Value, E> {
        Ok(v.into())
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Value, A::Error> {
        let mut values = Vec::new();
        while let Some(v) = seq.next_element_seed(Seed {
            nodes: self.nodes,
            depth: self.depth + 1,
        })? {
            values.push(v);
        }
        Ok(Value::Array(values))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut values = Map::new();
        while let Some(key) = map.next_key::<String>()? {
            *self.nodes += 1;
            if self.depth + 1 > 32 || *self.nodes > 50_000 {
                return Err(A::Error::custom("json_depth_or_node_bound"));
            }
            if values.contains_key(&key) {
                return Err(A::Error::custom("duplicate_json_key"));
            }
            let v = map.next_value_seed(Seed {
                nodes: self.nodes,
                depth: self.depth + 1,
            })?;
            values.insert(key, v);
        }
        Ok(Value::Object(values))
    }
}

pub fn parse(bytes: &[u8]) -> Result<Value, String> {
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let value = Seed {
        nodes: &mut 0,
        depth: 0,
    }
    .deserialize(&mut deserializer)
    .map_err(|e| format!("invalid_json:{e}"))?;
    deserializer
        .end()
        .map_err(|e| format!("invalid_json:{e}"))?;
    Ok(value)
}

pub fn canonical(value: &Value) -> Result<Vec<u8>, String> {
    fn write(v: &Value, out: &mut Vec<u8>) -> Result<(), String> {
        match v {
            Value::Object(map) => {
                // RFC 8785 orders unescaped property names by UTF-16 code units,
                // not UTF-8, Unicode scalar values or escaped JSON spellings.
                let mut keys: Vec<_> = map.keys().collect();
                keys.sort_by(|a, b| a.encode_utf16().cmp(b.encode_utf16()));
                out.push(b'{');
                for (i, key) in keys.iter().enumerate() {
                    if i > 0 {
                        out.push(b',');
                    }
                    serde_json::to_writer(&mut *out, key).map_err(|e| e.to_string())?;
                    out.push(b':');
                    write(&map[*key], out)?;
                }
                out.push(b'}');
            }
            Value::Array(values) => {
                out.push(b'[');
                for (i, item) in values.iter().enumerate() {
                    if i > 0 {
                        out.push(b',');
                    }
                    write(item, out)?;
                }
                out.push(b']');
            }
            Value::Number(n) => {
                let f = n.as_f64().ok_or("invalid_number")?;
                if !f.is_finite() || (f.fract() == 0. && f.abs() > MAX_SAFE) {
                    return Err("nonfinite_or_unsafe_number".into());
                }
                out.extend_from_slice(ryu_js::Buffer::new().format_finite(f).as_bytes());
            }
            _ => serde_json::to_writer(&mut *out, v).map_err(|e| e.to_string())?,
        }
        if out.len() > MAX_ARTIFACT {
            return Err("canonical_artifact_size_bound".into());
        }
        Ok(())
    }
    let mut bytes = Vec::new();
    write(value, &mut bytes)?;
    if bytes.len() > MAX_ARTIFACT {
        return Err("canonical_artifact_size_bound".into());
    }
    Ok(bytes)
}
pub fn raw_hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
pub fn hash(value: &Value) -> Result<String, String> {
    Ok(raw_hash(&canonical(value)?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_jcs_vectors_and_refusals() {
        let cases: Value = serde_json::from_str(include_str!(
            "../../../../tests/fixtures/cw-g02/canonical.json"
        ))
        .unwrap();
        for case in cases.as_array().unwrap() {
            let raw = case["input"].as_str().unwrap();
            let result = parse(raw.as_bytes()).and_then(|v| canonical(&v));
            if case["canonical"].is_null() {
                assert!(result.is_err(), "{}", case["name"]);
            } else {
                assert_eq!(
                    String::from_utf8(result.unwrap()).unwrap(),
                    case["canonical"].as_str().unwrap(),
                    "{}",
                    case["name"]
                );
            }
        }
    }
}
