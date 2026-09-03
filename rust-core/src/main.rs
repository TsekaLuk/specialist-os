use specialist_core::{cache_key, validate_input};
use std::env;

fn main() {
    let args: Vec<String> = env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("cache-key") if args.len() == 7 => println!(
            "{}",
            cache_key(&args[2], &args[3], &args[4], &args[5], &args[6])
        ),
        Some("validate") if args.len() == 5 => {
            let size = args[2].parse().unwrap_or(u64::MAX);
            let max = args[3].parse().unwrap_or(0);
            let regular = args[4] == "true";
            match validate_input(size, max, regular) {
                Ok(()) => println!("ok"),
                Err(message) => {
                    eprintln!("{}", message);
                    std::process::exit(2);
                }
            }
        }
        _ => {
            eprintln!("usage: specialist-core cache-key <input-sha256> <capability> <provider> <model> <options-json>");
            eprintln!("       specialist-core validate <size-bytes> <max-bytes> <regular-file:true|false>");
            std::process::exit(2);
        }
    }
}
