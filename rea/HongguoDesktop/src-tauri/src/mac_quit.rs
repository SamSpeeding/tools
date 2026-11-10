//! Route native macOS Quit (including Dock Quit) through the task confirmation.
//! Tao 0.37 forwards applicationWillTerminate but has no shouldTerminate hook.
use objc2::{
    runtime::{AnyClass, AnyObject, Sel},
    sel, MainThreadMarker,
};
use objc2_app_kit::NSApplication;
use std::{
    ffi::{c_char, c_void},
    sync::{atomic::Ordering, OnceLock},
};
use tauri::{Emitter, Manager};

static APP: OnceLock<tauri::AppHandle> = OnceLock::new();

#[link(name = "objc")]
extern "C" {
    fn class_addMethod(
        class: *const AnyClass,
        selector: Sel,
        implementation: *const c_void,
        types: *const c_char,
    ) -> bool;
}

extern "C" fn should_terminate(
    _delegate: *mut AnyObject,
    _selector: Sel,
    _sender: *mut AnyObject,
) -> usize {
    if let Some(app) = APP.get() {
        if app
            .state::<super::Backend>()
            .quitting
            .load(Ordering::SeqCst)
        {
            return 1; // NSTerminateNow
        }
        let _ = app.emit("exit-request", ());
        return 0; // NSTerminateCancel; quit_app exits after confirmation/cleanup.
    }
    1
}

pub fn install(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let mtm = MainThreadMarker::new().ok_or("macOS quit hook requires main thread")?;
    let delegate = NSApplication::sharedApplication(mtm)
        .delegate()
        .ok_or("Missing application delegate")?;
    let object: &AnyObject = (*delegate).as_ref();
    APP.set(app.clone())
        .map_err(|_| "Quit hook already installed")?;
    // AppKit declares NSUInteger applicationShouldTerminate:(NSApplication*).
    // Register only this absent selector on our application's existing delegate.
    let added = unsafe {
        class_addMethod(
            object.class(),
            sel!(applicationShouldTerminate:),
            should_terminate as *const c_void,
            c"Q@:@".as_ptr(),
        )
    };
    if !added {
        return Err("Unable to install macOS quit confirmation".into());
    }
    Ok(())
}
