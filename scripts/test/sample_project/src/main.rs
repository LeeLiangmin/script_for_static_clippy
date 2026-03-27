// 故意包含一些 clippy 能检测到的问题
fn main() {
    let x = needless_return();
    println!("x = {}", x);

    let y = let_and_return();
    println!("y = {}", y);

    // clippy::manual_is_ascii_check
    let c = 'a';
    let _is_lower = c >= 'a' && c <= 'z';

    // clippy::needless_range_loop
    let v = vec![1, 2, 3, 4, 5];
    for i in 0..v.len() {
        println!("{}", v[i]);
    }

    // clippy::single_match
    let opt: Option<i32> = Some(42);
    match opt {
        Some(val) => println!("val = {}", val),
        _ => {},
    }

    // clippy::bool_comparison
    let flag = true;
    if flag == true {
        println!("flag is true");
    }
}

// clippy::needless_return
fn needless_return() -> i32 {
    return 42;
}

// clippy::let_and_return
fn let_and_return() -> i32 {
    let result = 1 + 2;
    result
}
