/**
 * Interview Coach - Keyboard Hotkeys Hook
 * 
 * Hotkeys:
 * - Ctrl/Cmd + Enter: Generate response
 * - Ctrl/Cmd + Shift + C: Copy answer
 * - Ctrl/Cmd + S: Save session
 * - Ctrl/Cmd + O: Open sessions modal
 * - Ctrl/Cmd + ,: Open settings
 * - Ctrl/Cmd + 1-4: Switch style
 * - Escape: Close modals
 */

import { useEffect, useCallback } from 'react';

interface HotkeyHandlers {
  onGenerate?: () => void;
  onCopy?: () => void;
  onSaveSession?: () => void;
  onOpenSessions?: () => void;
  onOpenSettings?: () => void;
  onSetStyle?: (style: 'executive' | 'commercial' | 'technical' | 'mixed') => void;
  onCloseModals?: () => void;
}

export function useHotkeys(handlers: HotkeyHandlers) {
  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
    const cmdKey = isMac ? event.metaKey : event.ctrlKey;
    
    // Ignore if typing in input/textarea
    const target = event.target as HTMLElement;
    const isTyping = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable;
    
    // Escape - always handle
    if (event.key === 'Escape') {
      handlers.onCloseModals?.();
      return;
    }
    
    // Don't handle other hotkeys while typing (except Escape)
    if (isTyping) return;
    
    // Cmd/Ctrl + Enter: Generate response
    if (cmdKey && event.key === 'Enter') {
      event.preventDefault();
      handlers.onGenerate?.();
      return;
    }
    
    // Cmd/Ctrl + Shift + C: Copy answer
    if (cmdKey && event.shiftKey && event.key === 'C') {
      event.preventDefault();
      handlers.onCopy?.();
      return;
    }
    
    // Cmd/Ctrl + S: Save session
    if (cmdKey && event.key === 's') {
      event.preventDefault();
      handlers.onSaveSession?.();
      return;
    }
    
    // Cmd/Ctrl + O: Open sessions
    if (cmdKey && event.key === 'o') {
      event.preventDefault();
      handlers.onOpenSessions?.();
      return;
    }
    
    // Cmd/Ctrl + ,: Open settings
    if (cmdKey && event.key === ',') {
      event.preventDefault();
      handlers.onOpenSettings?.();
      return;
    }
    
    // Cmd/Ctrl + 1-4: Switch style
    if (cmdKey && event.key >= '1' && event.key <= '4') {
      event.preventDefault();
      const styles = ['executive', 'commercial', 'technical', 'mixed'] as const;
      const index = parseInt(event.key) - 1;
      handlers.onSetStyle?.(styles[index]);
      return;
    }
  }, [handlers]);
  
  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);
}

// Hotkey display helper
export function formatHotkey(key: string, shift = false): string {
  const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
  const cmd = isMac ? '⌘' : 'Ctrl';
  
  if (shift) {
    return `${cmd}⇧${key.toUpperCase()}`;
  }
  return `${cmd}${key.toUpperCase()}`;
}

// Hotkey hints for UI
export const HOTKEY_HINTS = {
  generate: '⌘↵',
  copy: '⌘⇧C',
  save: '⌘S',
  sessions: '⌘O',
  settings: '⌘,',
  style1: '⌘1',
  style2: '⌘2',
  style3: '⌘3',
  style4: '⌘4',
  close: 'Esc',
};
