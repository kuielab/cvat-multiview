// Copyright (C) 2024 CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';
import { useSelector, useDispatch } from 'react-redux';
import Input from 'antd/lib/input';
import Checkbox from 'antd/lib/checkbox';
import Tag from 'antd/lib/tag';
import Collapse from 'antd/lib/collapse';

import { CombinedState } from 'reducers';
import { updateAnnotationsAsync } from 'actions/annotation-actions';
import ObjectsListContainer from 'containers/annotation-page/standard-workspace/objects-side-bar/objects-list';

const { Panel } = Collapse;
const { TextArea } = Input;

/**
 * MultiviewObjectsList Component
 *
 * Extends the standard objects list with multiview-specific fields:
 * - view_id: Visual badge showing which camera view (1-5)
 * - description: Text area for annotation notes
 * - needs_review: Checkbox flag for review status
 *
 * This component wraps the standard ObjectsListContainer and adds
 * additional UI for multiview custom fields.
 */
export default function MultiviewObjectsList(): JSX.Element {
    const dispatch = useDispatch();
    const activatedStateID = useSelector((state: CombinedState) => state.annotation.annotations.activatedStateID);
    const states = useSelector((state: CombinedState) => state.annotation.annotations.states);

    // Find the currently selected annotation
    const selectedAnnotation = states.find((state: any) => state.clientID === activatedStateID);

    // Handle description update
    const handleDescriptionChange = (e: React.ChangeEvent<HTMLTextAreaElement>): void => {
        if (selectedAnnotation) {
            try {
                // Update the annotation state
                selectedAnnotation.description = e.target.value;
                // Dispatch update action
                dispatch(updateAnnotationsAsync([selectedAnnotation]));
            } catch (error) {
                console.error('Failed to update description:', error);
            }
        }
    };

    // Handle needs_review toggle
    const handleNeedsReviewChange = (e: any): void => {
        if (selectedAnnotation) {
            try {
                // Update the annotation state
                selectedAnnotation.needs_review = e.target.checked;
                // Dispatch update action
                dispatch(updateAnnotationsAsync([selectedAnnotation]));
            } catch (error) {
                console.error('Failed to update needs_review:', error);
            }
        }
    };

    // Get view ID color based on view number
    const getViewColor = (viewId: number): string => {
        const colors = ['#1890ff', '#52c41a', '#faad14', '#f5222d', '#722ed1'];
        return colors[(viewId - 1) % colors.length];
    };

    return (
        <div className='cvat-multiview-objects-list'>
            {/* Standard objects list */}
            <ObjectsListContainer />

            {/* Multiview-specific fields panel */}
            {selectedAnnotation && (
                <Collapse
                    bordered={false}
                    defaultActiveKey={['multiview-fields']}
                    className='cvat-multiview-fields-panel'
                    style={{ marginTop: 8 }}
                >
                    <Panel
                        header='Multiview Properties'
                        key='multiview-fields'
                        className='cvat-multiview-fields-collapse'
                    >
                        <div className='cvat-multiview-field-group'>
                            {/* View ID Badge */}
                            <div className='cvat-multiview-field'>
                                <span className='cvat-multiview-field-label'>Camera View:</span>
                                {selectedAnnotation.viewId ? (
                                    <Tag
                                        color={getViewColor(selectedAnnotation.viewId)}
                                        style={{ marginLeft: 8, fontWeight: 'bold' }}
                                    >
                                        View {selectedAnnotation.viewId}
                                    </Tag>
                                ) : (
                                    <Tag color='default' style={{ marginLeft: 8 }}>
                                        Not Set
                                    </Tag>
                                )}
                            </div>

                            {/* Description Text Area */}
                            <div className='cvat-multiview-field' style={{ marginTop: 12 }}>
                                <span className='cvat-multiview-field-label'>Description:</span>
                                <TextArea
                                    placeholder='Add notes about this annotation...'
                                    autoSize={{ minRows: 2, maxRows: 6 }}
                                    value={selectedAnnotation.description || ''}
                                    onChange={handleDescriptionChange}
                                    style={{ marginTop: 4 }}
                                />
                            </div>

                            {/* Needs Review Checkbox */}
                            <div className='cvat-multiview-field' style={{ marginTop: 12 }}>
                                <Checkbox
                                    checked={selectedAnnotation.needs_review || false}
                                    onChange={handleNeedsReviewChange}
                                >
                                    <span className='cvat-multiview-field-label'>Needs Review</span>
                                </Checkbox>
                            </div>
                        </div>
                    </Panel>
                </Collapse>
            )}

            {/* Styling */}
            <style>{`
                .cvat-multiview-objects-list {
                    height: 100%;
                    display: flex;
                    flex-direction: column;
                }

                .cvat-multiview-fields-panel {
                    background-color: #1e1e1e;
                }

                .cvat-multiview-fields-panel .ant-collapse-header {
                    color: #fff !important;
                    background-color: #2a2a2a !important;
                    border-radius: 4px !important;
                }

                .cvat-multiview-fields-panel .ant-collapse-content {
                    background-color: #252525 !important;
                    border-top: 1px solid #333 !important;
                }

                .cvat-multiview-field-group {
                    padding: 8px;
                }

                .cvat-multiview-field {
                    display: flex;
                    flex-direction: column;
                }

                .cvat-multiview-field-label {
                    font-size: 12px;
                    font-weight: 600;
                    color: #ccc;
                    margin-bottom: 4px;
                }

                .cvat-multiview-field textarea {
                    background-color: #1a1a1a !important;
                    border-color: #444 !important;
                    color: #fff !important;
                }

                .cvat-multiview-field textarea:focus {
                    border-color: #ff6b00 !important;
                    box-shadow: 0 0 0 2px rgba(255, 107, 0, 0.2) !important;
                }

                .cvat-multiview-field .ant-checkbox-wrapper {
                    color: #fff;
                }

                .cvat-multiview-field .ant-checkbox-checked .ant-checkbox-inner {
                    background-color: #ff6b00;
                    border-color: #ff6b00;
                }
            `}</style>
        </div>
    );
}
