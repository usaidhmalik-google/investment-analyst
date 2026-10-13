import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Composer } from './Composer';

describe('Composer', () => {
  it('submits on Enter with the selected strategy and clears the input', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} onStop={() => {}} isStreaming={false} />);
    const input = screen.getByLabelText('Your request');
    fireEvent.click(screen.getByLabelText('Momentum'));
    fireEvent.change(input, { target: { value: 'Brief me on NVDA' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledWith('Brief me on NVDA', 'momentum');
    expect(input).toHaveValue('');
  });

  it('does not submit on Shift+Enter or when empty', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} onStop={() => {}} isStreaming={false} />);
    const input = screen.getByLabelText('Your request');
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.change(input, { target: { value: 'line 1' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Send request' })).toBeEnabled();
  });

  it('shows a Stop button while streaming', () => {
    const onStop = vi.fn();
    render(<Composer onSend={() => {}} onStop={onStop} isStreaming />);
    fireEvent.click(screen.getByRole('button', { name: 'Stop generating' }));
    expect(onStop).toHaveBeenCalled();
  });
});
